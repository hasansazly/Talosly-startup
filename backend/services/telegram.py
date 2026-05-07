import html
import logging
import re
from typing import Any

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)


class TelegramService:
    """Talosly Telegram notification service."""

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
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            logger.info("Talosly Telegram credentials are not configured")
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

    def _format_message(self, protocol: dict[str, Any], transaction: dict[str, Any], score_result: Any) -> str:
        risk_score = getattr(score_result, "risk_score", None) if not isinstance(score_result, dict) else score_result.get("risk_score")
        p_name = html.escape(str(protocol.get("name") or "Unknown Protocol"))
        s_val = html.escape(str(risk_score or "0"))
        h_val = html.escape(str(transaction.get("tx_hash") or "No Hash Available"))
        msg = f"🚨 <b>New Risk Alert</b> 🚨\n<b>Protocol:</b> {p_name}\n<b>Score:</b> <code>{s_val}</code>\n<b>TX:</b> <code>{h_val}</code>"
        return msg

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
