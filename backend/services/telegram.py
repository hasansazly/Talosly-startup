import html
import logging
import re
from typing import Any

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)


class TelegramService:
    """Talosly Telegram notification service."""

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

                logger.warning("Talosly Telegram HTML send failed: status=%s body=%s", response.status_code, response.text[:500])
                plain_payload = {
                    "chat_id": settings.telegram_chat_id,
                    "text": self._format_plain_message(message),
                    "disable_web_page_preview": True,
                }
                retry = await client.post(url, json=plain_payload)
                if retry.is_success:
                    return True

                logger.warning("Talosly Telegram plain send failed: status=%s body=%s", retry.status_code, retry.text[:500])
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

    def _shorten(self, address: str) -> str:
        if len(address) <= 18:
            return address
        return f"{address[:10]}...{address[-6:]}"
