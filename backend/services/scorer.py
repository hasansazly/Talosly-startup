import json
import logging
import re
from inspect import isawaitable
from typing import Any

from openai import AsyncOpenAI, OpenAIError
from pydantic import ValidationError

from backend.config import settings
from backend.models import RiskScoreResponse
from backend.services.etherscan import get_address_label
from .blacklist import BLACKLIST, EXPLOIT_TARGETS

logger = logging.getLogger(__name__)

KNOWN_SAFE_ADDRESSES = {
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d",
    "0xe592427a0aece92de3edee1f18e0157c05861564",
    "0x1111111254eeb25477b68fb85ed929f73a960582",
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45",
    "0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f",
}

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


def norm(addr: str | None) -> str | None:
    return addr.lower() if addr else None


def value_as_eth(value: Any) -> float:
    if value is None:
        return 0
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            if value.startswith("0x"):
                return int(value, 16) / 1_000_000_000_000_000_000
            return float(value)
        except ValueError:
            return 0
    return 0


class TransactionScorer:
    """Talosly OpenAI-powered risk scoring service."""

    def __init__(self) -> None:
        self.client = AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    async def _get_wallet_reputation(self, address: str) -> dict[str, bool]:
        """Checks wallet age and ENS reputation when a Web3 provider is attached."""
        w3 = getattr(self, "w3", None)
        if w3 is None:
            return {"is_new": False, "has_no_ens": False}

        tx_count_result = w3.eth.get_transaction_count(address)
        tx_count = await tx_count_result if isawaitable(tx_count_result) else tx_count_result

        ens_name = None
        ens = getattr(w3, "ens", None)
        if ens is not None:
            ens_result = ens.name(address)
            ens_name = await ens_result if isawaitable(ens_result) else ens_result

        return {
            "is_new": tx_count < 5,
            "has_no_ens": ens_name is None,
        }

    def pre_screen(self, transaction: dict[str, Any]) -> RiskScoreResponse | None:
        tx_hash = transaction["tx_hash"]
        from_address = norm(transaction.get("from_address") or transaction.get("from"))
        to_address = norm(transaction.get("to_address") or transaction.get("to"))
        value_eth = value_as_eth(transaction.get("value_eth", transaction.get("value", 0)))
        input_data = transaction.get("input_data", transaction.get("input", "")) or ""
        gas_used = self._parse_int(transaction.get("gas_used", transaction.get("gas", 0)))
        selector = self._function_selector(input_data)

        # High-confidence hits return immediately to save deeper analysis costs.
        if from_address in BLACKLIST or to_address in BLACKLIST:
            return RiskScoreResponse(
                tx_hash=tx_hash,
                risk_score=98,
                risk_summary="High-risk: Known malicious entity.",
                risk_factors=["BLACKLISTED_ADDRESS"],
            )

        if to_address in EXPLOIT_TARGETS:
            return RiskScoreResponse(
                tx_hash=tx_hash,
                risk_score=82,
                risk_summary="Known exploit target contract interaction",
                risk_factors=["KNOWN_EXPLOIT_TARGET"],
            )

        behavior_result = self._detect_exploit_behavior(
            tx_hash=tx_hash,
            to_address=to_address,
            value_eth=value_eth,
            input_data=input_data,
            gas_used=gas_used,
            selector=selector,
        )
        if behavior_result is not None:
            return behavior_result

        if norm(from_address) == norm(to_address) and from_address is not None:
            return RiskScoreResponse(
                tx_hash=tx_hash,
                risk_score=78,
                risk_summary="Self-transfer detected",
                risk_factors=["SELF_TRANSFER"],
            )

        # Large value transaction - instant 85
        if value_eth > 1000:
            return RiskScoreResponse(
                tx_hash=tx_hash,
                risk_score=85,
                risk_summary="Large value transaction detected",
                risk_factors=["LARGE_VALUE_TRANSACTION"],
            )

        # Exploiters often test contracts with 0-value, high-data transactions.
        if value_eth == 0 and len(input_data or "") >= 200:
            return RiskScoreResponse(
                tx_hash=tx_hash,
                risk_score=72,
                risk_summary="Zero value with large payload",
                risk_factors=["PROBE_PATTERN"],
            )

        # Nothing caught - send to OpenAI
        return None

    def _detect_exploit_behavior(
        self,
        *,
        tx_hash: str,
        to_address: str | None,
        value_eth: float,
        input_data: str,
        gas_used: int,
        selector: str,
    ) -> RiskScoreResponse | None:
        if to_address in KNOWN_SAFE_ADDRESSES:
            return None

        indicators: list[str] = []
        score = 0

        flash_loan_selectors = {
            "5cffe9de",
            "ab9c4b5d",
            "e0232b42",
            "490e6cbc",
            "d9d98ce4",
            "61461954",
        }
        if selector in flash_loan_selectors:
            score += 45
            indicators.append("FLASH_LOAN_SELECTOR")

        if value_eth == 0 and selector and selector != "00000000":
            score += 35
            indicators.append("ZERO_VALUE_CONTRACT_CALL")

        if gas_used > 2_000_000:
            score += 35
            indicators.append("EXTREME_GAS_USAGE")
        elif gas_used > 500_000:
            score += 25
            indicators.append("HIGH_GAS_EXECUTION")

        if value_eth == 0 and len(input_data) >= 200:
            score += 20
            indicators.append("LARGE_PAYLOAD_PROBE")

        if selector == "095ea7b3" and "f" * 64 in input_data.lower():
            score += 50
            indicators.append("MAX_APPROVAL")

        if selector == "23b872dd":
            score += 20
            indicators.append("TRANSFER_FROM")

        if selector in {"3659cfe6", "4f1ef286"}:
            score += 55
            indicators.append("PROXY_UPGRADE")

        if value_eth > 1000:
            score += 40
            indicators.append("LARGE_VALUE_TRANSACTION")

        if "ZERO_VALUE_CONTRACT_CALL" in indicators and (
            "HIGH_GAS_EXECUTION" in indicators or "EXTREME_GAS_USAGE" in indicators
        ):
            score = max(score, 85)

        if score < 70 or not indicators:
            return None

        return RiskScoreResponse(
            tx_hash=tx_hash,
            risk_score=min(score, 98),
            risk_summary=f"Exploit behavior detected: {', '.join(indicators[:2]).replace('_', ' ').lower()}",
            risk_factors=indicators[:3],
        )

    def _function_selector(self, input_data: str) -> str:
        clean = (input_data or "").lower()
        if clean.startswith("0x"):
            clean = clean[2:]
        return clean[:8]

    def _parse_int(self, value: Any) -> int:
        if value is None:
            return 0
        if isinstance(value, bool):
            return 0
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value, 16) if value.startswith("0x") else int(value)
            except ValueError:
                return 0
        return 0

    async def score_transaction(self, transaction: dict[str, Any], protocol: dict[str, Any]) -> RiskScoreResponse:
        # Pre-screen before calling OpenAI, and before checking OpenAI config.
        pre_result = self.pre_screen(transaction)
        if pre_result is not None:
            # Pre-screen hits still pass through behavioral multipliers before final return.
            pre_result = await self._apply_behavioral_multiplier(
                pre_result,
                transaction.get("from_address") or transaction.get("from"),
            )
            return self._apply_score_overrides(pre_result)

        if not self.client:
            return RiskScoreResponse(
                tx_hash=transaction["tx_hash"],
                risk_score=50,
                risk_summary="Scoring unavailable",
                risk_factors=["OpenAI API key not configured"],
            )

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
                result = RiskScoreResponse(tx_hash=transaction["tx_hash"], **parsed)
                result = await self._apply_behavioral_multiplier(
                    result,
                    transaction.get("from_address") or transaction.get("from"),
                )
                return self._apply_score_overrides(result)
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

    def _apply_score_overrides(self, result: RiskScoreResponse) -> RiskScoreResponse:
        if result.risk_score >= 70 and "PROBE_PATTERN" in result.risk_factors:
            result.risk_score = max(result.risk_score, 85)
        return result

    async def _apply_behavioral_multiplier(self, result: RiskScoreResponse, from_address: str | None) -> RiskScoreResponse:
        if not from_address:
            return result

        reputation = await self._get_wallet_reputation(from_address)
        etherscan_data = await get_address_label(from_address)

        if reputation["is_new"] or etherscan_data["is_new_wallet"]:
            result.risk_score = min(result.risk_score + 10, 100)
            self._append_risk_factor(result, "NEW_WALLET")

        if reputation["has_no_ens"]:
            result.risk_score = min(result.risk_score + 5, 100)
            self._append_risk_factor(result, "NO_ENS_IDENTITY")

        if etherscan_data["funded_by_tornado"]:
            result.risk_score = min(result.risk_score + 20, 100)
            self._append_risk_factor(result, "TORNADO_FUNDED")

        if etherscan_data["is_dangerous"]:
            result.risk_score = min(result.risk_score + 20, 100)
            self._append_risk_factor(result, "ETHERSCAN_DANGER_LABEL")

        return result

    def _append_risk_factor(self, result: RiskScoreResponse, factor: str) -> None:
        if factor not in result.risk_factors and len(result.risk_factors) < 3:
            result.risk_factors.append(factor)

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
