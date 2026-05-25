"""Layer 5 alert orchestration.

This module owns the final alert decision after Layer 3 and Layer 4 have
already decided a transaction is worth deeper handling. It deliberately wraps
the existing DB and Telegram contracts instead of replacing them.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from backend.services.logger import logger


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _dedupe_window_seconds() -> int:
    return int(os.environ.get("LAYER5_DEDUPE_WINDOW_S", "300"))


def _confidence_gate_enabled() -> bool:
    return _env_bool("LAYER5_CONFIDENCE_GATE", True)


@dataclass(frozen=True)
class RoutingDecision:
    should_alert: bool
    reason: str
    channel: str
    enriched_score: int
    layer3_score: float
    layer4_verdict: str
    layer4_probability: float
    layer4_confidence: str


@dataclass(frozen=True)
class AlertProcessResult:
    score_saved: bool
    alert_created: bool
    telegram_sent: bool
    alert_id: int | None
    decision: RoutingDecision


class EnrichedScoreResult:
    """Duck-types RiskScoreResponse for the existing Telegram service."""

    def __init__(self, original: Any, risk_score: int, risk_summary: str, risk_factors: list[str]) -> None:
        self._original = original
        self.tx_hash = getattr(original, "tx_hash", "")
        self.risk_score = risk_score
        self.risk_summary = risk_summary
        self.risk_factors = risk_factors

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)


def _layer4_attr(layer4: Any, name: str, default: Any) -> Any:
    return getattr(layer4, name, default) if layer4 is not None else default


def routing_decision(
    score_result: Any,
    layer3: dict[str, Any] | None,
    layer4: Any | None,
    threshold: int,
    recently_alerted: bool,
) -> RoutingDecision:
    risk_score = int(getattr(score_result, "risk_score", 0) or 0)
    layer3_score = float((layer3 or {}).get("ensemble_score", 0.0) or 0.0)
    verdict = str(_layer4_attr(layer4, "verdict", "unknown") or "unknown")
    probability = float(_layer4_attr(layer4, "exploit_probability", 0.0) or 0.0)
    confidence = str(_layer4_attr(layer4, "confidence", "low") or "low")
    action = str(_layer4_attr(layer4, "recommended_action", "monitor") or "monitor")
    fallback = bool(_layer4_attr(layer4, "fallback_used", True))

    enriched_score = risk_score
    if layer4 is not None:
        if fallback:
            enriched_score = max(enriched_score, threshold)
        elif action == "alert":
            enriched_score = max(enriched_score, int(probability * 100), threshold)
        elif verdict == "exploit":
            enriched_score = max(enriched_score, int(probability * 100))
        elif verdict == "benign":
            enriched_score = min(enriched_score, 40)

    if recently_alerted:
        return RoutingDecision(
            False,
            "dedupe_suppressed",
            "suppressed",
            enriched_score,
            layer3_score,
            verdict,
            probability,
            confidence,
        )

    if enriched_score < threshold:
        return RoutingDecision(
            False,
            f"below_threshold_{enriched_score}<{threshold}",
            "suppressed",
            enriched_score,
            layer3_score,
            verdict,
            probability,
            confidence,
        )

    if (
        _confidence_gate_enabled()
        and layer4 is not None
        and not fallback
        and verdict == "benign"
        and confidence == "high"
        and action != "alert"
    ):
        return RoutingDecision(
            False,
            "layer4_benign_high_confidence",
            "monitor_only",
            enriched_score,
            layer3_score,
            verdict,
            probability,
            confidence,
        )

    if layer4 is not None and not fallback and action == "monitor":
        return RoutingDecision(
            False,
            "layer4_action_monitor",
            "monitor_only",
            enriched_score,
            layer3_score,
            verdict,
            probability,
            confidence,
        )

    return RoutingDecision(
        True,
        "all_gates_passed",
        "telegram",
        enriched_score,
        layer3_score,
        verdict,
        probability,
        confidence,
    )


def enrich_risk_summary(score_result: Any, layer3: dict[str, Any] | None, layer4: Any | None) -> str:
    base = str(getattr(score_result, "risk_summary", "") or "No summary available")
    details: list[str] = []

    if layer3:
        details.append(
            f"Layer 3 ML score {float(layer3.get('ensemble_score', 0.0) or 0.0):.2f}"
            f" ({layer3.get('mode', 'unknown')})"
        )

    if layer4 is not None:
        fallback = bool(getattr(layer4, "fallback_used", False))
        fallback_label = " fallback" if fallback else ""
        details.append(
            "Layer 4"
            f"{fallback_label}: {getattr(layer4, 'verdict', 'unknown')}"
            f" ({float(getattr(layer4, 'exploit_probability', 0.0) or 0.0):.0%},"
            f" {getattr(layer4, 'confidence', 'low')} confidence,"
            f" {getattr(layer4, 'attack_type', 'unknown')})"
        )
        reasoning = str(getattr(layer4, "reasoning", "") or "")
        if reasoning and not fallback:
            details.append(reasoning[:180])

    if not details:
        return base
    return f"{base}\n\nML/LLM signals:\n" + "\n".join(details)


def enrich_risk_factors(score_result: Any, layer4: Any | None) -> list[str]:
    factors = [str(item) for item in list(getattr(score_result, "risk_factors", []) or [])]
    if layer4 is None or bool(getattr(layer4, "fallback_used", False)):
        return factors[:3]

    for signal in list(getattr(layer4, "sub_signals", []) or [])[:3]:
        name = signal.get("signal") or signal.get("feature") or "layer4_signal"
        contribution = signal.get("risk_contribution") or "risk"
        factor = f"L4_{str(contribution).upper()}_{str(name).upper()}"
        if factor not in factors:
            factors.append(factor)
    return factors[:3]


class AlertOrchestrator:
    """Final alert gateway for DB persistence and Telegram delivery."""

    def __init__(self, database: Any, telegram: Any) -> None:
        self.database = database
        self.telegram = telegram
        self._recent_alerts: dict[str, float] = {}

    async def process(
        self,
        *,
        tx_id: int,
        protocol: dict[str, Any],
        transaction: dict[str, Any],
        score_result: Any,
        layer3: dict[str, Any] | None = None,
        layer4: Any | None = None,
        threshold: int,
    ) -> AlertProcessResult:
        tx_hash = str(transaction.get("tx_hash") or transaction.get("hash") or getattr(score_result, "tx_hash", ""))
        self._prune_recent_alerts()
        decision = routing_decision(
            score_result=score_result,
            layer3=layer3,
            layer4=layer4,
            threshold=threshold,
            recently_alerted=tx_hash in self._recent_alerts,
        )

        summary = enrich_risk_summary(score_result, layer3, layer4)
        factors = enrich_risk_factors(score_result, layer4)
        enriched = EnrichedScoreResult(score_result, decision.enriched_score, summary, factors)

        score_saved = await self._save_score(tx_id, enriched)
        logger.info(
            "layer5.routing",
            tx_hash=tx_hash[:18],
            channel=decision.channel,
            reason=decision.reason,
            enriched_score=decision.enriched_score,
            layer3_score=decision.layer3_score,
            layer4_verdict=decision.layer4_verdict,
            layer4_probability=decision.layer4_probability,
        )

        if not decision.should_alert:
            return AlertProcessResult(score_saved, False, False, None, decision)

        alert_id = await self._insert_alert(tx_id, enriched)
        if alert_id is None:
            return AlertProcessResult(score_saved, False, False, None, decision)

        telegram_sent = await self._send_telegram(protocol, transaction, enriched)
        if telegram_sent:
            self._recent_alerts[tx_hash] = time.time()
            await self._mark_telegram_sent(alert_id)

        return AlertProcessResult(score_saved, True, telegram_sent, alert_id, decision)

    async def _save_score(self, tx_id: int, score_result: EnrichedScoreResult) -> bool:
        try:
            await self.database.update_transaction_score(
                tx_id,
                score_result.risk_score,
                score_result.risk_summary,
                score_result.risk_factors,
            )
            return True
        except Exception as exc:
            logger.error("layer5.score_save.failed", error=str(exc))
            return False

    async def _insert_alert(self, tx_id: int, score_result: EnrichedScoreResult) -> int | None:
        try:
            alert_id = await self.database.insert_alert(
                tx_id,
                score_result.risk_score,
                score_result.risk_summary,
            )
            return int(alert_id)
        except Exception as exc:
            logger.error("layer5.alert_insert.failed", error=str(exc))
            return None

    async def _send_telegram(
        self,
        protocol: dict[str, Any],
        transaction: dict[str, Any],
        score_result: EnrichedScoreResult,
    ) -> bool:
        try:
            sent = await self.telegram.send_alert(protocol, transaction, score_result)
            if not sent and getattr(self.telegram, "last_send_suppressed", False):
                logger.info("layer5.telegram.suppressed")
            elif not sent:
                logger.warning("layer5.telegram.failed")
            return bool(sent)
        except Exception as exc:
            logger.error("layer5.telegram.exception", error=str(exc))
            return False

    async def _mark_telegram_sent(self, alert_id: int) -> None:
        try:
            await self.database.mark_telegram_sent(alert_id)
        except Exception as exc:
            logger.error("layer5.telegram_mark.failed", alert_id=alert_id, error=str(exc))

    def _prune_recent_alerts(self) -> None:
        cutoff = time.time() - _dedupe_window_seconds()
        self._recent_alerts = {
            tx_hash: last_seen
            for tx_hash, last_seen in self._recent_alerts.items()
            if last_seen > cutoff
        }
