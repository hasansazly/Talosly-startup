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
        score = getattr(score_result, "risk_score", None) if not isinstance(score_result, dict) else score_result.get("risk_score")
        summary = getattr(score_result, "risk_summary", "") if not isinstance(score_result, dict) else score_result.get("risk_summary", "")
        factors = getattr(score_result, "risk_factors", []) if not isinstance(score_result, dict) else score_result.get("risk_factors", [])
        tx_hash = transaction.get("tx_hash", "")
        factor_lines = "\n".join(f"• {html.escape(str(factor))}" for factor in factors[:3])
        return f"""🚨 <b>Talosly Alert</b> — Risk Score: {html.escape(str(score))}/100

<b>Protocol:</b> {html.escape(str(protocol.get('name', 'Unknown')))}
<b>TX Hash:</b> <code>{html.escape(self._shorten(tx_hash))}</code>
<b>From:</b> <code>{html.escape(self._shorten(transaction.get('from_address') or ''))}</code>
<b>Value:</b> {html.escape(str(transaction.get('value_eth', 0)))} ETH
<b>Summary:</b> {html.escape(str(summary))}

<b>Risk Factors:</b>
{factor_lines}

🔍 <a href="https://etherscan.io/tx/{html.escape(tx_hash)}">View on Etherscan</a>

— Talosly Security Monitor"""

    def _shorten(self, address: str) -> str:
        if len(address) <= 18:
            return address
        return f"{address[:10]}...{address[-6:]}"
