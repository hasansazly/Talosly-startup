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
from data.load_known_hacks import KnownHacksDB
from .blacklist import BLACKLIST, EXPLOIT_TARGETS

logger = logging.getLogger(__name__)
KNOWN_HACKS = KnownHacksDB()

KNOWN_SAFE_ADDRESSES = {
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d",
    "0xe592427a0aece92de3edee1f18e0157c05861564",
    "0x1111111254eeb25477b68fb85ed929f73a960582",
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45",
    "0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f",
}

HIGH_VALUE_VAULTS = {
    # Euler eToken / exploit-path contracts used in replay fixtures.
    "0xebc29199c817dc47ba12e3f86102564d640cbf99",
    "0x27182842e098f60e3d576794a5bffb0777e025d3",
    # Common DeFi vaults / lending pools where abnormal asset flow matters.
    "0xba12222222228d8ba445958a75a0704d566bf2c8",
    "0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2",
    "0x9f8f72aa9304c8b593d555f12ef6589cc3a579a2",
}

KNOWN_BRIDGE_CONTRACTS = {
    # Cross-chain message processors / bridge replicas where forged-message bugs
    # can look like valid calls unless protocol invariants are checked.
    "0x5d94309e5a0090b165fa4181519701637b6daeba",
    # Nomad ERC20 bridge escrow. Large token releases from bridge escrows are
    # materially different from ordinary token transfers.
    "0x88a69b4e698a4b090df6cf5bd7b2d47325ad30a3",
}

METHOD_SELECTORS = {
    "863df8af": "donateToReserves",
    "928bc4b2": "process",
    "d450e04c": "verifyHeaderAndExecuteTx",
    "42d96952": "liquidateWithFlashLoan",
    "40c10f19": "mint",
    "1249c58b": "mint",
    "f2fde38b": "transferOwnership",
    "3659cfe6": "upgradeTo",
    "4f1ef286": "upgradeToAndCall",
}

KNOWN_SAFE_VAULT_SELECTORS = {
    "573ade81",  # Aave repay
    "617ba037",  # Aave supply/deposit
    "a415bcad",  # Aave borrow
    "1cff79cd",  # Maker vault open
}

BRIDGE_MESSAGE_SELECTORS = {
    "928bc4b2",  # process(bytes)
}

CROSS_CHAIN_RELAY_SELECTORS = {
    "d450e04c",  # verifyHeaderAndExecuteTx(...)
}

ERC20_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

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


def get_severity(score: int) -> str:
    if score >= 70:
        return "CRITICAL"
    if score >= 40:
        return "WARNING"
    return "INFO"


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
        bridge_context = self._bridge_context(transaction, input_data)

        # High-confidence hits return immediately to save deeper analysis costs.
        known_hack = KNOWN_HACKS.get(tx_hash)
        if known_hack is not None:
            return RiskScoreResponse(
                tx_hash=tx_hash,
                risk_score=100,
                risk_summary=f"Known exploit transaction: {known_hack.protocol}",
                risk_factors=["KNOWN_EXPLOIT_TRANSACTION", known_hack.attack_type.upper()],
            )

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

        if to_address in KNOWN_SAFE_ADDRESSES:
            return None

        if to_address in HIGH_VALUE_VAULTS and selector in KNOWN_SAFE_VAULT_SELECTORS:
            return None

        behavior_result = self._detect_exploit_behavior(
            transaction=transaction,
            tx_hash=tx_hash,
            to_address=to_address,
            value_eth=value_eth,
            input_data=input_data,
            gas_used=gas_used,
            selector=selector,
            bridge_context=bridge_context,
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

        # Large simple transfers are notable, but should not alert without another exploit signal.
        if value_eth > 1000:
            return RiskScoreResponse(
                tx_hash=tx_hash,
                risk_score=50,
                risk_summary="Large value transaction detected",
                risk_factors=["LARGE_VALUE_TRANSACTION"],
            )

        # Nothing caught - send to OpenAI
        return None

    def _detect_exploit_behavior(
        self,
        *,
        transaction: dict[str, Any],
        tx_hash: str,
        to_address: str | None,
        value_eth: float,
        input_data: str,
        gas_used: int,
        selector: str,
        bridge_context: dict[str, bool],
    ) -> RiskScoreResponse | None:
        indicators: list[str] = []
        score = 0
        method_name = self._method_name(transaction, selector)
        is_reverted = self._is_reverted(transaction)
        method_lower = method_name.lower()

        flash_loan_selectors = {
            "5cffe9de",
            "ab9c4b5d",
            "e0232b42",
            "490e6cbc",
            "d9d98ce4",
            "61461954",
        }
        if selector in flash_loan_selectors:
            score += 30
            indicators.append("FLASH_LOAN")

        if "donate" in method_name.lower():
            score += 25
            indicators.append("DONATION_PATTERN")

        if selector in BRIDGE_MESSAGE_SELECTORS or method_name.lower() in {"process", "processmessage"}:
            score += 30
            indicators.append("CROSS_CHAIN_MESSAGE_PROCESS")

        if bridge_context["embedded_message_process"]:
            score += 35
            indicators.append("EMBEDDED_BRIDGE_MESSAGE")

        if selector in CROSS_CHAIN_RELAY_SELECTORS or method_name.lower() == "verifyheaderandexecutetx":
            score += 30
            indicators.append("CROSS_CHAIN_RELAY_EXECUTION")

        if to_address in KNOWN_BRIDGE_CONTRACTS:
            score += 25
            indicators.append("KNOWN_BRIDGE_CONTRACT")

        if bridge_context["known_bridge_log_emitter"]:
            score += 25
            indicators.append("BRIDGE_EVENT_EMITTED")

        if bridge_context["bridge_token_outflow"]:
            score += 35
            indicators.append("BRIDGE_TOKEN_OUTFLOW")

        if bridge_context["large_token_transfer"]:
            score += 20
            indicators.append("LARGE_TOKEN_TRANSFER")

        if (
            ("CROSS_CHAIN_MESSAGE_PROCESS" in indicators or "EMBEDDED_BRIDGE_MESSAGE" in indicators)
            and ("KNOWN_BRIDGE_CONTRACT" in indicators or "BRIDGE_EVENT_EMITTED" in indicators)
        ):
            score += 20
            indicators.append("BRIDGE_INVARIANT_RISK")

        if "CROSS_CHAIN_RELAY_EXECUTION" in indicators and len(input_data) > 1000:
            score += 25
            indicators.append("PRIVILEGED_RELAY_PAYLOAD")

        if len(input_data) > 2000 and selector not in flash_loan_selectors:
            score += 15
            indicators.append("CALLDATA_COMPLEXITY")

        common_token_selectors = {"23b872dd"}
        if (
            value_eth == 0
            and selector
            and selector != "00000000"
            and selector not in common_token_selectors
            and selector not in flash_loan_selectors
        ):
            score += 35
            indicators.append("ZERO_VALUE_CONTRACT_CALL")

        if to_address in HIGH_VALUE_VAULTS:
            score += 20
            indicators.append("HIGH_VALUE_VAULT")

        if gas_used > 2_000_000:
            score += 40
            indicators.append("EXTREME_GAS_USAGE")
        elif gas_used > 500_000:
            score += 25
            indicators.append("HIGH_GAS_EXECUTION")
        elif selector in flash_loan_selectors and gas_used >= 200_000:
            score += 10
            indicators.append("MODERATE_GAS_EXECUTION")

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

        if selector in {"f2fde38b", "79ba5097"} or "transferownership" in method_name.lower():
            score += 55
            indicators.append("ACCESS_CONTROL_CHANGE")

        if selector in {"40c10f19", "1249c58b"} or method_name.lower() == "mint":
            score += 55
            indicators.append("UNAUTHORIZED_MINT_SIGNAL")

        if value_eth > 100 and selector:
            score += 40
            indicators.append("LARGE_VALUE_TRANSACTION")

        price_impact = max(
            self._parse_float(transaction.get("price_impact_pct")),
            self._parse_float(transaction.get("spot_twap_deviation_pct")),
            self._parse_float(transaction.get("price_deviation_pct")),
            self._parse_float(transaction.get("oracle_deviation_pct")),
        )
        if price_impact > 5:
            score += 40
            indicators.append("PRICE_IMPACT")

        if transaction.get("liquidity_delta_mismatch") or transaction.get("tick_state_mismatch"):
            score += 45
            indicators.append("AMM_STATE_MISMATCH")

        if selector in flash_loan_selectors and value_eth == 0:
            score += 15
            indicators.append("ZERO_VALUE_FLASH_LOAN")

        if any(term in method_lower for term in ("liquidat", "repay")):
            score += 10
            indicators.append("LIQUIDATION_FLOW")

        wallet_age_minutes = self._parse_float(transaction.get("wallet_age_minutes"))
        if wallet_age_minutes and wallet_age_minutes <= 10:
            score += 20
            indicators.append("BRAND_NEW_WALLET")

        balance_change_usd = self._balance_change_usd(transaction)
        if balance_change_usd >= 1_000_000:
            score += 50
            indicators.append("BALANCE_JUMP")

        repeated_calls = self._parse_int(
            transaction.get("same_contract_call_count")
            or transaction.get("repeated_contract_calls")
            or transaction.get("max_reentrant_calls")
        )
        if repeated_calls >= 3:
            score += 53
            indicators.append("REENTRANCY_PATTERN")

        if is_reverted:
            score = max(score - 25, 0)
            indicators = self._append_ordered_indicator(indicators, "REVERTED_TX")

        if "FLASH_LOAN" in indicators and self._has_only_moderate_flash_loan_signals(indicators):
            score = min(score, 65)

        if "LIQUIDATION_FLOW" in indicators and not self._has_critical_context(indicators):
            score = min(score, 65)

        if score < 40 or not indicators:
            return None

        return RiskScoreResponse(
            tx_hash=tx_hash,
            risk_score=min(score, 100),
            risk_summary=f"Exploit behavior detected: {', '.join(indicators[:2]).replace('_', ' ').lower()}",
            risk_factors=indicators[:3],
        )

    def _function_selector(self, input_data: str) -> str:
        clean = (input_data or "").lower()
        if clean.startswith("0x"):
            clean = clean[2:]
        return clean[:8]

    def _method_name(self, transaction: dict[str, Any], selector: str) -> str:
        return str(transaction.get("method_name") or transaction.get("method") or METHOD_SELECTORS.get(selector, ""))

    def _bridge_context(self, transaction: dict[str, Any], input_data: str) -> dict[str, bool]:
        clean_input = (input_data or "").lower()
        clean_input = clean_input[2:] if clean_input.startswith("0x") else clean_input
        embedded_bridge_address = any(address[2:] in clean_input for address in KNOWN_BRIDGE_CONTRACTS)
        embedded_bridge_selector = any(selector in clean_input for selector in BRIDGE_MESSAGE_SELECTORS | CROSS_CHAIN_RELAY_SELECTORS)

        known_bridge_log_emitter = False
        bridge_token_outflow = False
        large_token_transfer = False

        for log in transaction.get("logs") or []:
            log_address = norm(log.get("address"))
            if log_address in KNOWN_BRIDGE_CONTRACTS:
                known_bridge_log_emitter = True

            topics = [str(topic).lower() for topic in (log.get("topics") or [])]
            if not topics or topics[0] != ERC20_TRANSFER_TOPIC:
                continue

            from_address = self._topic_address(topics[1] if len(topics) > 1 else None)
            to_address = self._topic_address(topics[2] if len(topics) > 2 else None)
            amount = self._parse_int(log.get("data"))

            if from_address in KNOWN_BRIDGE_CONTRACTS and to_address not in KNOWN_BRIDGE_CONTRACTS:
                bridge_token_outflow = True

            if amount >= 100_000_000:
                large_token_transfer = True

        return {
            "embedded_message_process": embedded_bridge_address and embedded_bridge_selector,
            "known_bridge_log_emitter": known_bridge_log_emitter,
            "bridge_token_outflow": bridge_token_outflow,
            "large_token_transfer": large_token_transfer,
        }

    def _topic_address(self, topic: str | None) -> str | None:
        if not topic:
            return None
        clean = topic.lower()
        if clean.startswith("0x"):
            clean = clean[2:]
        if len(clean) < 40:
            return None
        return f"0x{clean[-40:]}"

    def _is_reverted(self, transaction: dict[str, Any]) -> bool:
        status = transaction.get("status") or transaction.get("receipt_status")
        if isinstance(status, str):
            return status.lower() in {"0x0", "0", "false", "failed", "reverted"}
        return status in {0, False}

    def _append_ordered_indicator(self, indicators: list[str], indicator: str) -> list[str]:
        return indicators if indicator in indicators else [*indicators, indicator]

    def _has_only_moderate_flash_loan_signals(self, indicators: list[str]) -> bool:
        moderate = {
            "FLASH_LOAN",
            "ZERO_VALUE_FLASH_LOAN",
            "MODERATE_GAS_EXECUTION",
            "LARGE_PAYLOAD_PROBE",
            "REVERTED_TX",
        }
        return set(indicators).issubset(moderate)

    def _has_critical_context(self, indicators: list[str]) -> bool:
        critical = {
            "BLACKLISTED_ADDRESS",
            "BRIDGE_INVARIANT_RISK",
            "PRIVILEGED_RELAY_PAYLOAD",
            "PRICE_IMPACT",
            "AMM_STATE_MISMATCH",
            "BALANCE_JUMP",
            "UNAUTHORIZED_MINT_SIGNAL",
            "REENTRANCY_PATTERN",
        }
        return bool(set(indicators) & critical)

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

    def _parse_float(self, value: Any) -> float:
        if value is None or isinstance(value, bool):
            return 0
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.rstrip("%"))
            except ValueError:
                return 0
        return 0

    def _balance_change_usd(self, transaction: dict[str, Any]) -> float:
        direct_change = self._parse_float(transaction.get("attacker_balance_change_usd") or transaction.get("balance_change_usd"))
        if direct_change:
            return direct_change

        before = self._parse_float(transaction.get("attacker_balance_before_usd"))
        after = self._parse_float(transaction.get("attacker_balance_after_usd"))
        return max(after - before, 0)

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
                risk_score=15,
                risk_summary="No exploit signals detected",
                risk_factors=["NO_SIGNALS_DETECTED"],
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
