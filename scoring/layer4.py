"""Layer 4 LLM oracle for transactions escalated by Layer 3.

Layer 4 always returns an OracleResult. If the LLM is disabled, times out,
returns malformed JSON, or raises an exception, the oracle fails open and
returns an alert-worthy fallback result because Layer 3 already decided the
transaction crossed the escalation threshold.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from backend.config import settings
from backend.services.logger import logger

ATTACK_TAXONOMY = {
    "flash_loan",
    "reentrancy",
    "oracle_manipulation",
    "price_manipulation",
    "governance_attack",
    "access_control",
    "sandwich_attack",
    "private_key_compromise",
    "bridge_exploit",
    "integer_overflow",
    "front_running",
    "unknown",
}

INPUT_COST_PER_1M = 0.150
OUTPUT_COST_PER_1M = 0.600


@dataclass
class OracleResult:
    tx_hash: str
    exploit_probability: float
    confidence: str
    verdict: str
    reasoning: str
    attack_type: str
    sub_signals: list[dict[str, Any]]
    recommended_action: str
    cost_usd: float
    model: str
    latency_ms: float
    fallback_used: bool = False
    layer3_score: float = 0.0

    @property
    def should_alert(self) -> bool:
        return self.recommended_action == "alert"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _cost_usd(prompt_tokens: int, completion_tokens: int) -> float:
    return round(
        (prompt_tokens / 1_000_000 * INPUT_COST_PER_1M)
        + (completion_tokens / 1_000_000 * OUTPUT_COST_PER_1M),
        6,
    )


def _system_prompt() -> str:
    taxonomy = ", ".join(sorted(ATTACK_TAXONOMY))
    return f"""You are a DeFi security oracle inside a real-time exploit detection system.

You receive precomputed signals from Layer 2 and Layer 3. Produce a structured,
auditable risk assessment. Do not reveal hidden reasoning. Provide a concise
evidence-based rationale only.

Return ONLY valid JSON with this schema:
{{
  "exploit_probability": <float 0.0-1.0>,
  "confidence": <"high"|"medium"|"low">,
  "verdict": <"exploit"|"suspicious"|"benign">,
  "reasoning": <2-3 concise evidence-based sentences>,
  "attack_type": <one of: {taxonomy}>,
  "sub_signals": [
    {{"signal": <feature_name>, "value": <number>, "risk_contribution": <"high"|"medium"|"low">, "note": <one sentence>}}
  ],
  "recommended_action": <"alert"|"monitor"|"skip">
}}

When uncertain, prefer "suspicious" over "benign" because false negatives are
more damaging than false positives in this security context."""


def _user_prompt(tx_hash: str, features: dict[str, Any], layer3: dict[str, Any]) -> str:
    shap_top = layer3.get("shap_top") or []
    shap_lines = "\n".join(
        f"- {signal.get('feature')}: value={signal.get('value')}, shap={float(signal.get('shap') or 0):+.4f}"
        for signal in shap_top
    ) or "- none"
    feature_lines = "\n".join(f"- {key}: {value}" for key, value in sorted(features.items()))
    return f"""Transaction: {tx_hash}

Layer 3:
- ensemble_score: {float(layer3.get('ensemble_score') or 0):.4f}
- isolation_score: {float(layer3.get('isolation_score') or 0):.4f}
- gbm_prob: {float(layer3.get('gbm_prob') or 0):.4f}
- bayesian_prob: {float(layer3.get('bayesian_prob') or 0):.4f}
- confidence: [{float(layer3.get('confidence_low') or 0):.4f}, {float(layer3.get('confidence_high') or 0):.4f}]
- mode: {layer3.get('mode', 'unknown')}

Top SHAP drivers:
{shap_lines}

Layer 2 features:
{feature_lines}

This transaction crossed the Layer 3 escalation threshold. Return the strict JSON assessment."""


def _strip_json_fence(raw: str) -> str:
    clean = raw.strip()
    if clean.startswith("```"):
        lines = clean.splitlines()
        clean = "\n".join(lines[1:])
    if clean.endswith("```"):
        clean = clean[:-3]
    return clean.strip()


def _parse_oracle_response(
    raw: str,
    *,
    tx_hash: str,
    layer3: dict[str, Any],
    cost_usd: float,
    latency_ms: float,
    model: str,
) -> OracleResult:
    payload = json.loads(_strip_json_fence(raw))
    if not isinstance(payload, dict):
        raise ValueError("oracle response must be a JSON object")

    probability = _clamp(float(payload.get("exploit_probability", 0.5)))
    confidence = str(payload.get("confidence") or "medium")
    if confidence not in {"high", "medium", "low"}:
        confidence = "medium"

    verdict = str(payload.get("verdict") or "suspicious")
    if verdict not in {"exploit", "suspicious", "benign"}:
        verdict = "suspicious"

    attack_type = str(payload.get("attack_type") or "unknown")
    if attack_type not in ATTACK_TAXONOMY:
        attack_type = "unknown"

    action = str(payload.get("recommended_action") or "monitor")
    if action not in {"alert", "monitor", "skip"}:
        action = "monitor"

    sub_signals = payload.get("sub_signals") or []
    if not isinstance(sub_signals, list):
        sub_signals = []

    return OracleResult(
        tx_hash=tx_hash,
        exploit_probability=round(probability, 4),
        confidence=confidence,
        verdict=verdict,
        reasoning=str(payload.get("reasoning") or "")[:500],
        attack_type=attack_type,
        sub_signals=sub_signals[:8],
        recommended_action=action,
        cost_usd=cost_usd,
        model=model,
        latency_ms=latency_ms,
        fallback_used=False,
        layer3_score=float(layer3.get("ensemble_score") or 0.0),
    )


def _fallback_result(tx_hash: str, layer3: dict[str, Any], reason: str, latency_ms: float) -> OracleResult:
    layer3_score = float(layer3.get("ensemble_score") or 0.0)
    logger.warning("layer4.oracle.fallback", tx_hash=tx_hash[:18], reason=reason, layer3_score=layer3_score)
    sub_signals = layer3.get("shap_top") or []
    return OracleResult(
        tx_hash=tx_hash,
        exploit_probability=round(max(layer3_score, 0.60), 4),
        confidence="low",
        verdict="suspicious",
        reasoning=(
            f"Layer 4 oracle unavailable ({reason}). Layer 3 score {layer3_score:.3f} "
            "crossed the escalation threshold, so Talosly is raising an alert as a fail-open precaution."
        ),
        attack_type="unknown",
        sub_signals=sub_signals[:8] if isinstance(sub_signals, list) else [],
        recommended_action="alert",
        cost_usd=0.0,
        model="fallback",
        latency_ms=latency_ms,
        fallback_used=True,
        layer3_score=layer3_score,
    )


class Layer4Oracle:
    """Async OpenAI-backed oracle with fail-open fallback semantics."""

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        max_tokens: int | None = None,
        cost_log_file: str | Path | None = None,
    ) -> None:
        self.enabled = settings.layer4_enabled if enabled is None else enabled
        self.model = model or settings.layer4_model
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else settings.layer4_timeout_seconds
        self.max_tokens = max_tokens if max_tokens is not None else settings.layer4_max_tokens
        self.cost_log_file = Path(cost_log_file or settings.layer4_cost_log_file)
        self._client = None
        self._init_client(api_key)

    def _init_client(self, api_key: str | None) -> None:
        if not self.enabled:
            logger.info("layer4.oracle.disabled")
            return
        resolved_key = api_key if api_key is not None else settings.openai_api_key
        if not resolved_key:
            logger.warning("layer4.oracle.disabled", reason="missing_openai_api_key")
            self.enabled = False
            return
        try:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=resolved_key)
        except ImportError:
            logger.warning("layer4.oracle.disabled", reason="openai_package_missing")
            self.enabled = False

    async def analyze(self, tx_hash: str, features: dict[str, Any], layer3: dict[str, Any]) -> OracleResult:
        started = time.perf_counter()
        if not self.enabled or self._client is None:
            return _fallback_result(tx_hash, layer3, "oracle_disabled", self._latency(started))

        try:
            return await asyncio.wait_for(
                self._call_openai(tx_hash, features, layer3, started),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            return _fallback_result(tx_hash, layer3, f"timeout_{self.timeout_seconds}s", self._latency(started))
        except Exception as exc:
            return _fallback_result(tx_hash, layer3, f"{type(exc).__name__}:{exc}", self._latency(started))

    async def _call_openai(
        self,
        tx_hash: str,
        features: dict[str, Any],
        layer3: dict[str, Any],
        started: float,
    ) -> OracleResult:
        response = await self._client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=0.1,
            messages=[
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": _user_prompt(tx_hash, features, layer3)},
            ],
        )
        latency_ms = self._latency(started)
        raw = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        cost_usd = _cost_usd(prompt_tokens, completion_tokens)

        try:
            result = _parse_oracle_response(
                raw,
                tx_hash=tx_hash,
                layer3=layer3,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
                model=self.model,
            )
        except Exception as exc:
            result = _fallback_result(tx_hash, layer3, f"parse_error:{exc}", latency_ms)
            result.cost_usd = cost_usd

        self._log_cost(
            {
                "ts": time.time(),
                "tx_hash": tx_hash,
                "model": self.model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd": cost_usd,
                "latency_ms": latency_ms,
                "verdict": result.verdict,
                "fallback": result.fallback_used,
                "layer3_score": layer3.get("ensemble_score", 0),
            }
        )
        logger.info(
            "layer4.oracle.result",
            tx_hash=tx_hash[:18],
            verdict=result.verdict,
            probability=result.exploit_probability,
            confidence=result.confidence,
            action=result.recommended_action,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            fallback=result.fallback_used,
        )
        return result

    def _log_cost(self, record: dict[str, Any]) -> None:
        with contextlib.suppress(Exception):
            self.cost_log_file.parent.mkdir(parents=True, exist_ok=True)
            with self.cost_log_file.open("a") as file:
                file.write(json.dumps(record, default=str) + "\n")

    @staticmethod
    def _latency(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 2)


_oracle: Layer4Oracle | None = None


def get_oracle() -> Layer4Oracle:
    global _oracle
    if _oracle is None:
        _oracle = Layer4Oracle()
    return _oracle
