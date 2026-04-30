import json
import logging
import re
from typing import Any

from anthropic import AsyncAnthropic
from pydantic import ValidationError

from backend.config import settings
from backend.models import RiskScoreResponse

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Talosly, a DeFi security analysis engine. Your job is to analyze Ethereum transactions and assign a risk score from 0 to 100, where:

0-30  = Low risk (routine transfer, standard swap, normal liquidity operation)
31-60 = Medium risk (unusual parameters, large value, complex interaction)
61-70 = Elevated risk (suspicious pattern, high value, unusual gas, potential exploit signature)
71-100 = High risk (likely attack, flash loan exploit pattern, reentrancy signature, large drain, address match to known exploiter)

Respond ONLY with a valid JSON object. No markdown, no explanation outside the JSON.

Schema:
{
  "risk_score": <integer 0-100>,
  "risk_summary": "<one sentence, max 120 chars, plain English>",
  "risk_factors": ["<factor 1>", "<factor 2>", "<factor 3 max>"]
}

Risk factors to consider:
- Transaction value (ETH amount relative to protocol TVL context)
- Input data complexity (number of function calls, unusual selectors)
- Gas usage (extremely high or low gas relative to value)
- Known exploit patterns in input data (reentrancy, flash loan, delegatecall abuse)
- From address reputation (if determinable from context)
- Time pattern (if metadata provided)
- Interaction type (direct ETH transfer vs complex contract call)

Be conservative. When uncertain, lean toward a higher score. A false positive alert is better than a missed exploit."""


class TransactionScorer:
    """Talosly Claude-powered risk scoring service."""

    def __init__(self) -> None:
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key) if settings.anthropic_api_key else None

    async def score_transaction(self, transaction: dict[str, Any], protocol: dict[str, Any]) -> RiskScoreResponse:
        if not self.client:
            return RiskScoreResponse(
                tx_hash=transaction["tx_hash"],
                risk_score=50,
                risk_summary="Scoring unavailable",
                risk_factors=["Anthropic API key not configured"],
            )
        prompt = self._build_prompt(transaction, protocol)
        for attempt in range(2):
            try:
                message = await self.client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=300,
                    temperature=0,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                )
                content = "".join(block.text for block in message.content if getattr(block, "type", "") == "text")
                parsed = self._parse_response(content)
                return RiskScoreResponse(tx_hash=transaction["tx_hash"], **parsed)
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                if attempt == 1:
                    logger.warning("Talosly scoring parse failed: %s", exc)
            except Exception as exc:
                logger.exception("Talosly scoring failed: %s", exc)
                break
        return RiskScoreResponse(
            tx_hash=transaction["tx_hash"],
            risk_score=50,
            risk_summary="Scoring unavailable",
            risk_factors=["Claude scoring failed"],
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
        score = data.get("risk_score")
        if not isinstance(score, int) or score < 0 or score > 100:
            raise ValueError("risk_score must be an integer from 0 to 100")
        return {
            "risk_score": score,
            "risk_summary": str(data.get("risk_summary", "No summary available"))[:120],
            "risk_factors": list(data.get("risk_factors", []))[:3],
        }
