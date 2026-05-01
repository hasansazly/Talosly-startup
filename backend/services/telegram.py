import html
import logging
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
                response = await client.post(
                    url,
                    json={
                        "chat_id": settings.telegram_chat_id,
                        "text": message,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                )
                response.raise_for_status()
            return True
        except Exception as exc:
            logger.warning("Talosly Telegram send failed: %s", exc)
            return False

    def _format_message(self, protocol: dict[str, Any], transaction: dict[str, Any], score_result: Any) -> str:
        risk_score = getattr(score_result, "risk_score", None) if not isinstance(score_result, dict) else score_result.get("risk_score")
        protocol_name = protocol.get("name", "Unknown")
        tx_hash = transaction.get("tx_hash", "")
        message = (
            "<b>🚨 New Risk Alert 🚨</b>\n\n"
            f"<b>Protocol:</b> {html.escape(str(protocol_name))}\n"
            f"<b>Score:</b> <code>{html.escape(str(risk_score))}</code>\n"
            f"<b>TX:</b> <code>{html.escape(tx_hash)}</code>"
        )
        return message

    def _shorten(self, address: str) -> str:
        if len(address) <= 18:
            return address
        return f"{address[:10]}...{address[-6:]}"
