import html
import logging
import re
from datetime import datetime
from typing import Any

import httpx

from backend import database as db
from backend.config import settings
from backend.services.scorer import get_severity

logger = logging.getLogger(__name__)


class TelegramService:
    """Talosly Telegram notification service."""

    def __init__(self) -> None:
        self.last_send_suppressed = False

    async def send_message(self, text: str, chat_id: str | None = None) -> bool:
        target_chat_id = chat_id or settings.telegram_chat_id
        if not settings.telegram_bot_token or not target_chat_id:
            logger.info("Talosly Telegram credentials are not configured")
            return False
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    url,
                    json={
                        "chat_id": target_chat_id,
                        "text": text,
                        "disable_web_page_preview": True,
                    },
                )
                if response.is_success:
                    return True
                self._log_send_failure("plain", response)
                return False
        except httpx.HTTPError as exc:
            logger.warning("Talosly Telegram request failed: %s", exc.__class__.__name__)
            return False
        except Exception as exc:
            logger.warning("Talosly Telegram send failed: %s", exc.__class__.__name__)
            return False

    async def send_alert(self, protocol: dict[str, Any], transaction: dict[str, Any], score_result: Any) -> bool:
        self.last_send_suppressed = False
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            logger.info("Talosly Telegram credentials are not configured")
            return False
        risk_score = self._get_risk_score(score_result)
        severity = get_severity(risk_score)
        protocol_address = str(protocol.get("address") or "")
        if not await self.should_send_alert(protocol_address, severity):
            self.last_send_suppressed = True
            logger.info("Talosly Telegram alert suppressed by dedupe window")
            return False
        message = self._format_message(protocol, transaction, score_result)
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                logger.info("DEBUG TELEGRAM MSG: %s", message)
                payload = {
                    "chat_id": settings.telegram_chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                }
                response = await client.post(url, json=payload)
                if response.is_success:
                    return True

                self._log_send_failure("HTML", response)
                plain_payload = {
                    "chat_id": settings.telegram_chat_id,
                    "text": self._format_plain_message(message),
                    "disable_web_page_preview": True,
                }
                retry = await client.post(url, json=plain_payload)
                if retry.is_success:
                    return True

                self._log_send_failure("plain", retry)
                return False
        except httpx.HTTPError as exc:
            logger.warning("Talosly Telegram request failed: %s", exc.__class__.__name__)
            return False
        except Exception as exc:
            logger.warning("Talosly Telegram send failed: %s", exc.__class__.__name__)
            return False

    async def should_send_alert(self, protocol_address: str, severity: str) -> bool:
        """Return True when a Telegram notification should be sent for this protocol."""
        if not protocol_address:
            return True
        try:
            pool = await db.get_pool()
            row = await pool.fetchrow(
                """
                SELECT alerts.created_at, alerts.risk_score
                FROM alerts
                JOIN transactions ON transactions.id = alerts.transaction_id
                JOIN protocols ON protocols.id = transactions.protocol_id
                WHERE LOWER(protocols.address) = LOWER($1)
                  AND alerts.telegram_sent = TRUE
                ORDER BY alerts.created_at DESC
                LIMIT 1
                """,
                protocol_address,
            )
        except Exception as exc:
            logger.warning("Talosly Telegram dedupe check failed: %s", exc.__class__.__name__)
            return True

        if not row:
            return True

        created_at = row["created_at"]
        if created_at.tzinfo is not None:
            created_at = created_at.replace(tzinfo=None)
        if (datetime.utcnow() - created_at).total_seconds() > 300:
            return True

        previous_severity = get_severity(int(row["risk_score"] or 0))
        if previous_severity == "CRITICAL":
            return False
        if previous_severity == "WARNING" and severity != "CRITICAL":
            return False
        return True

    def _format_message(self, protocol: dict[str, Any], transaction: dict[str, Any], score_result: Any) -> str:
        risk_score = self._get_risk_score(score_result)
        risk_summary = getattr(score_result, "risk_summary", None) if not isinstance(score_result, dict) else score_result.get("risk_summary")
        severity = get_severity(risk_score)
        icons = {
            "CRITICAL": "🔴 <b>[CRITICAL THREAT]</b>",
            "WARNING": "🟡 <b>[WARNING]</b>",
            "INFO": "🔵 <b>[INFO]</b>",
        }
        p_name = html.escape(str(protocol.get("name") or "Unknown Protocol"))
        s_val = html.escape(str(risk_score or "0"))
        h_val = html.escape(str(transaction.get("tx_hash") or "No Hash Available"))
        summary = html.escape(str(risk_summary or "No summary available"))
        tx_url = f"https://etherscan.io/tx/{h_val}" if h_val != "No Hash Available" else "No Hash Available"
        msg = (
            f"{icons[severity]}\n"
            f"<b>Protocol:</b> {p_name}\n"
            f"<b>Risk Score:</b> <code>{s_val}/100</code>\n"
            f"<b>Summary:</b> {summary}\n"
            f"<b>View Tx:</b> {tx_url}"
        )
        return msg

    def _get_risk_score(self, score_result: Any) -> int:
        risk_score = getattr(score_result, "risk_score", None) if not isinstance(score_result, dict) else score_result.get("risk_score")
        return int(risk_score or 0)

    def _format_plain_message(self, message: str) -> str:
        return html.unescape(re.sub(r"</?[^>]+>", "", message))

    def _log_send_failure(self, mode: str, response: httpx.Response) -> None:
        body = response.text[:500]
        if response.status_code == 400 and "chat not found" in body.lower():
            logger.warning(
                "Talosly Telegram %s send failed: chat not found. Check TELEGRAM_CHAT_ID and confirm the bot has access to that chat.",
                mode,
            )
            return
        logger.warning("Talosly Telegram %s send failed: status=%s body=%s", mode, response.status_code, body)

    def _shorten(self, address: str) -> str:
        if len(address) <= 18:
            return address
        return f"{address[:10]}...{address[-6:]}"
