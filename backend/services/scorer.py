import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI, OpenAIError
from pydantic import ValidationError

from backend.config import settings
from backend.models import RiskScoreResponse

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are a DeFi security expert analyzing Ethereum transactions.

Score HIGH RISK (70-100) if you detect:
- Flash loan + price manipulation in same block
- Reentrancy pattern (same contract called 3+ times)
- Token approval > 1M to unknown contract
- Large drain: >50% of protocol liquidity leaving in one tx
- Known exploit signatures

Score MEDIUM RISK (40-69) if you detect:
- First interaction with this contract
- Transaction 10x larger than protocol average
- New wallet (< 10 previous transactions)
- Unusual token pairs

Score LOW RISK (0-39) if:
- Known wallet with normal history
- Transaction matches typical protocol behavior
- Small value relative to protocol TVL

Return ONLY this JSON:
{
  "score": 0-100,
  "reason": "one sentence max",
  "pattern": "FLASH_LOAN|REENTRANCY|DRAIN|APPROVAL|NORMAL",
  "action": "ALERT|WATCH|IGNORE"
}
"""


class TransactionScorer:
    """Talosly OpenAI-powered risk scoring service."""

    def __init__(self) -> None:
        self.client = AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    def pre_screen(self, transaction: dict[str, Any]) -> RiskScoreResponse | None:
        tx_hash = transaction["tx_hash"]
        to_address = (transaction.get("to_address") or "").lower()
        from_address = (transaction.get("from_address") or "").lower()
        value_eth = transaction.get("value_eth") or 0
        input_data = transaction.get("input_data") or ""

        # Known bad contracts - instant 99
        BLACKLIST: list[str] = [
            # add known exploit contracts here later
            # "0xabc123...",
        ]
        if to_address in BLACKLIST or from_address in BLACKLIST:
            return RiskScoreResponse(
                tx_hash=tx_hash,
                risk_score=99,
                risk_summary="Known exploit contract detected",
                risk_factors=["KNOWN_EXPLOIT_CONTRACT"],
            )

        # Large value transaction - instant 85
        if value_eth > 1000:
            return RiskScoreResponse(
                tx_hash=tx_hash,
                risk_score=85,
                risk_summary="Large value transaction detected",
                risk_factors=["LARGE_VALUE_TRANSACTION"],
            )

        # Suspicious input data length - possible exploit payload
        if len(input_data) >= 500:
            return RiskScoreResponse(
                tx_hash=tx_hash,
                risk_score=75,
                risk_summary="Large input data payload detected",
                risk_factors=["LARGE_INPUT_DATA"],
            )

        # Nothing caught - send to OpenAI
        return None

    async def score_transaction(self, transaction: dict[str, Any], protocol: dict[str, Any]) -> RiskScoreResponse:
        if not self.client:
            return RiskScoreResponse(
                tx_hash=transaction["tx_hash"],
                risk_score=50,
                risk_summary="Scoring unavailable",
                risk_factors=["OpenAI API key not configured"],
            )
        # Pre-screen before calling OpenAI
        pre_result = self.pre_screen(transaction)
        if pre_result is not None:
            return pre_result

        prompt = self._build_prompt(transaction, protocol)
        for attempt in range(2):
            try:
                message = await self.client.chat.completions.create(
                    model=settings.openai_model,
                    max_tokens=300,
                    temperature=0,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                )
                content = message.choices[0].message.content or ""
                parsed = self._parse_response(content)
                return RiskScoreResponse(tx_hash=transaction["tx_hash"], **parsed)
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                if attempt == 1:
                    logger.warning("Talosly scoring parse failed: %s", exc)
            except OpenAIError as exc:
                logger.exception("Talosly scoring failed: %s", exc)
                break
            except Exception as exc:
                logger.exception("Talosly unexpected scoring failure: %s", exc)
                break
        return RiskScoreResponse(
            tx_hash=transaction["tx_hash"],
            risk_score=50,
            risk_summary="Scoring unavailable",
            risk_factors=["OpenAI scoring failed"],
        )

    def _build_prompt(self, transaction: dict[str, Any], protocol: dict[str, Any]) -> str:
        return f"""Analyze this Ethereum transaction for the protocol: {protocol.get('name')} ({protocol.get('address')})

Transaction Hash: {transaction.get('tx_hash')}
From: {transaction.get('from_address')}
To: {transaction.get('to_address')}
Value: {transaction.get('value_eth')} ETH
Gas Used: {transaction.get('gas_used')}
Input Data (first 500 chars): {(transaction.get('input_data') or '')[:500]}
Block: {transaction.get('block_number')}

Assign a risk score and explain your reasoning."""

    def _parse_response(self, content: str) -> dict[str, Any]:
        cleaned = content.strip()
        fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.DOTALL)
        if fence:
            cleaned = fence.group(1).strip()
        data = json.loads(cleaned)
        if "score" in data:
            score = data.get("score")
            if not isinstance(score, int) or score < 0 or score > 100:
                raise ValueError("score must be an integer from 0 to 100")
            pattern = str(data.get("pattern", "NORMAL"))
            action = str(data.get("action", "WATCH"))
            return {
                "risk_score": score,
                "risk_summary": str(data.get("reason", "No summary available"))[:120],
                "risk_factors": [pattern, action][:3],
            }

        score = data.get("risk_score")
        if not isinstance(score, int) or score < 0 or score > 100:
            raise ValueError("risk_score must be an integer from 0 to 100")
        return {
            "risk_score": score,
            "risk_summary": str(data.get("risk_summary", "No summary available"))[:120],
            "risk_factors": list(data.get("risk_factors", []))[:3],
        }
