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
        tx_hash = str(transaction.get("tx_hash") or "No Hash Available")
        risk_summary = getattr(score_result, "risk_summary", None) if not isinstance(score_result, dict) else score_result.get("risk_summary")
        return await self.send_smart_alert(protocol, risk_score, tx_hash, risk_summary)

    async def send_smart_alert(
        self,
        protocol_data: dict[str, Any],
        score: int,
        tx_hash: str,
        reason: str | None = None,
    ) -> bool:
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            logger.info("Talosly Telegram credentials are not configured")
            return False
        severity = get_severity(int(score or 0))
        protocol_address = str(protocol_data.get("address") or "")
        state = await self._get_protocol_alert_state(protocol_address)
        now = datetime.utcnow()
        should_batch = self._should_batch_alert(state, severity, now)
        if should_batch:
            batch_count = int(state.get("alert_batch_count") or 1) + 1
            message_id = state.get("last_alert_message_id")
            text = self._format_batched_alert(severity, batch_count, tx_hash)
            if message_id and await self._edit_message(int(message_id), text):
                await self._save_protocol_alert_state(protocol_address, int(message_id), batch_count, severity, now)
                return True
            logger.info("Talosly Telegram batch edit failed; sending a fresh smart alert")

        text = self._format_new_smart_alert(protocol_data, int(score or 0), tx_hash, reason)
        message_id = await self._send_message_and_get_id(text)
        if message_id is None:
            return False
        await self._save_protocol_alert_state(protocol_address, message_id, 1, severity, now)
        return True

    async def _send_message_and_get_id(self, text: str) -> int | None:
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                logger.info("DEBUG TELEGRAM MSG: %s", text)
                payload = {
                    "chat_id": settings.telegram_chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                }
                response = await client.post(url, json=payload)
                if response.is_success:
                    return self._extract_message_id(response)

                self._log_send_failure("HTML", response)
                plain_payload = {
                    "chat_id": settings.telegram_chat_id,
                    "text": self._format_plain_message(text),
                    "disable_web_page_preview": True,
                }
                retry = await client.post(url, json=plain_payload)
                if retry.is_success:
                    return self._extract_message_id(retry)

                self._log_send_failure("plain", retry)
                return None
        except httpx.HTTPError as exc:
            logger.warning("Talosly Telegram request failed: %s", exc.__class__.__name__)
            return None
        except Exception as exc:
            logger.warning("Talosly Telegram send failed: %s", exc.__class__.__name__)
            return None

    async def _edit_message(self, message_id: int, text: str) -> bool:
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/editMessageText"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    url,
                    json={
                        "chat_id": settings.telegram_chat_id,
                        "message_id": message_id,
                        "text": text,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                )
                if response.is_success:
                    return True
                self._log_send_failure("edit", response)
                return False
        except httpx.HTTPError as exc:
            logger.warning("Talosly Telegram edit request failed: %s", exc.__class__.__name__)
            return False
        except Exception as exc:
            logger.warning("Talosly Telegram edit failed: %s", exc.__class__.__name__)
            return False

    async def _get_protocol_alert_state(self, protocol_address: str) -> dict[str, Any]:
        if not protocol_address:
            return {}
        try:
            pool = await db.get_pool()
            row = await pool.fetchrow(
                """
                SELECT last_alert_time, last_alert_message_id, alert_batch_count, last_alert_severity
                FROM protocols
                WHERE LOWER(address) = LOWER($1)
                """,
                protocol_address,
            )
            return dict(row) if row else {}
        except Exception as exc:
            logger.warning("Talosly Telegram smart alert state lookup failed: %s", exc.__class__.__name__)
            return {}

    async def _save_protocol_alert_state(
        self,
        protocol_address: str,
        message_id: int,
        batch_count: int,
        severity: str,
        sent_at: datetime,
    ) -> None:
        if not protocol_address:
            return
        try:
            pool = await db.get_pool()
            await pool.execute(
                """
                UPDATE protocols
                SET last_alert_time = $1,
                    last_alert_message_id = $2,
                    alert_batch_count = $3,
                    last_alert_severity = $4
                WHERE LOWER(address) = LOWER($5)
                """,
                sent_at,
                message_id,
                batch_count,
                severity,
                protocol_address,
            )
        except Exception as exc:
            logger.warning("Talosly Telegram smart alert state save failed: %s", exc.__class__.__name__)

    def _should_batch_alert(self, state: dict[str, Any], new_severity: str, now: datetime) -> bool:
        last_alert_time = state.get("last_alert_time")
        if not last_alert_time or not state.get("last_alert_message_id"):
            return False
        if last_alert_time.tzinfo is not None:
            last_alert_time = last_alert_time.replace(tzinfo=None)
        if (now - last_alert_time).total_seconds() >= 300:
            return False
        old_severity = str(state.get("last_alert_severity") or "")
        if new_severity == "CRITICAL" and old_severity == "WARNING":
            return False
        return True

    def _format_new_smart_alert(self, protocol_data: dict[str, Any], score: int, tx_hash: str, reason: str | None) -> str:
        protocol = html.escape(str(protocol_data.get("name") or "Unknown Protocol"))
        severity = get_severity(score)
        icons = {
            "CRITICAL": "🔴 <b>[CRITICAL THREAT]</b>",
            "WARNING": "🟡 <b>[WARNING]</b>",
            "INFO": "🔵 <b>[INFO]</b>",
        }
        safe_hash = html.escape(tx_hash)
        safe_reason = html.escape(str(reason or "No summary available"))
        return (
            f"{icons[severity]}\n"
            f"<b>Protocol:</b> {protocol}\n"
            f"<b>Risk Score:</b> <code>{score}/100</code>\n"
            f"<b>Summary:</b> {safe_reason}\n"
            f"<b>View Tx:</b> https://etherscan.io/tx/{safe_hash}"
        )

    def _format_batched_alert(self, severity: str, batch_count: int, tx_hash: str) -> str:
        icon = "🔴 [CRITICAL]" if severity == "CRITICAL" else "🟡 [WARNING]"
        safe_hash = html.escape(tx_hash)
        status = "Ongoing Attack" if severity == "CRITICAL" else "Continued Suspicious Activity"
        return f"{icon} {batch_count} additional transactions detected! Status: {status}. Latest Tx: {safe_hash}"

    def _extract_message_id(self, response: httpx.Response) -> int | None:
        try:
            data = response.json()
        except ValueError:
            return None
        message_id = data.get("result", {}).get("message_id")
        return int(message_id) if message_id is not None else None

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


async def send_smart_alert(protocol_data: dict[str, Any], score: int, tx_hash: str) -> bool:
    return await TelegramService().send_smart_alert(protocol_data, score, tx_hash)
