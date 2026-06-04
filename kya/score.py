"""KYA trust scoring built on Talosly's existing Layer 3 machinery."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from backend import database as db
from kya.config import kya_settings
from kya.features import build_feature_vector
from kya.ingest import AgentEvent
from kya.signals.changepoint import ChangepointSignal, compute_changepoint_signal
from kya.signals.mahalanobis import MahalanobisSignal, compute_mahalanobis_signal
from scoring.cost_tracker import CostTracker, CostReport, estimate_cost_usd
from scoring.layer3 import EnsembleResult, Layer3MLEnsemble, active_mode, reload_models, score_transaction

KYA_MODEL_DIR = Path("models/kya")
_default_kya_layer3: Layer3MLEnsemble | None = None


@dataclass(frozen=True)
class AgentTrustScore:
    agent_id: int
    trust_score: int
    risk_factors: list[str]
    shap_top: list[dict[str, Any]]
    confidence: float
    layer3: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def score_agent_event(
    agent_id: int,
    event: AgentEvent,
    baseline: dict[str, Any],
    layer3: Layer3MLEnsemble | None = None,
) -> AgentTrustScore:
    """Score one agent event and persist the resulting trust score."""
    features = build_feature_vector(event, baseline)
    scorer = layer3 or _get_kya_layer3()
    layer3_result = scorer.score(event.tx_hash, features)
    base_risk_probability = _kya_risk_probability(layer3_result, features)
    mahalanobis = compute_mahalanobis_signal(features, baseline.get("robust_stats") or {})
    changepoint = compute_changepoint_signal(layer3_result.isolation_score, baseline.get("cusum_state"))
    risk_probability = _fused_risk_probability(base_risk_probability, layer3_result, mahalanobis, changepoint)
    trust_score = int(round((1.0 - risk_probability) * 100))
    risk_factors = _risk_factors(features, layer3_result)
    shap_top = layer3_result.shap_top
    if mahalanobis.enabled or changepoint.enabled:
        risk_factors = _signal_risk_factors(risk_factors, mahalanobis, changepoint)
        shap_top = _signal_shap_top(shap_top, mahalanobis, changepoint)
    confidence = _confidence(layer3_result, baseline)

    score = AgentTrustScore(
        agent_id=agent_id,
        trust_score=max(0, min(trust_score, 100)),
        risk_factors=risk_factors,
        shap_top=shap_top,
        confidence=confidence,
        layer3=layer3_result.to_dict(),
    )
    await _persist_agent_score(score)
    if changepoint.enabled:
        await _persist_cusum_state(agent_id, changepoint.cusum_state)
    return score


def _get_kya_layer3() -> Layer3MLEnsemble:
    global _default_kya_layer3
    if _default_kya_layer3 is None:
        _default_kya_layer3 = Layer3MLEnsemble(
            model_dir=KYA_MODEL_DIR,
            bootstrap_if_missing=False,
        )
    return _default_kya_layer3


def _kya_risk_probability(result: EnsembleResult, features: dict[str, Any]) -> float:
    deviation_risk = 0.0
    if features.get("kya_new_counterparty"):
        deviation_risk += 0.20
    if features.get("kya_unseen_selector"):
        deviation_risk += 0.20
    if features.get("kya_off_hours"):
        deviation_risk += 0.10
    if features.get("kya_cadence_break"):
        deviation_risk += 0.15
    deviation_risk += min(float(features.get("kya_value_z_score") or 0.0) / 20, 0.25)
    return min(max(result.ensemble_score, deviation_risk), 1.0)


def _fused_risk_probability(
    base_risk_probability: float,
    result: EnsembleResult,
    mahalanobis: MahalanobisSignal,
    changepoint: ChangepointSignal,
) -> float:
    if not mahalanobis.enabled and not changepoint.enabled:
        return base_risk_probability

    weighted_signals = [(_weight(kya_settings.kya_w_base), float(result.isolation_score))]
    if mahalanobis.enabled:
        weighted_signals.append((_weight(kya_settings.kya_w_mahalanobis), mahalanobis.probability))
    if changepoint.enabled:
        weighted_signals.append((_weight(kya_settings.kya_w_changepoint), changepoint.changepoint_score))

    total_weight = sum(weight for weight, _value in weighted_signals)
    if total_weight <= 0:
        return base_risk_probability
    return min(max(sum(weight * value for weight, value in weighted_signals) / total_weight, 0.0), 1.0)


def _risk_factors(features: dict[str, Any], result: EnsembleResult) -> list[str]:
    factors = []
    if features.get("kya_new_counterparty"):
        factors.append("new_counterparty")
    if features.get("kya_unseen_selector"):
        factors.append("unseen_selector")
    if features.get("kya_off_hours"):
        factors.append("off_hours")
    if features.get("kya_cadence_break"):
        factors.append("cadence_break")
    if float(features.get("kya_value_z_score") or 0.0) >= 3.0:
        factors.append("value_outlier")
    for item in result.shap_top:
        feature = item.get("feature")
        if feature and feature not in factors and abs(float(item.get("shap") or 0.0)) > 0:
            factors.append(str(feature))
    return factors


def _signal_risk_factors(
    factors: list[str],
    mahalanobis: MahalanobisSignal,
    changepoint: ChangepointSignal,
) -> list[str]:
    updated = list(factors)
    if mahalanobis.enabled and "mahalanobis_anomaly" not in updated:
        updated.append("mahalanobis_anomaly")
    if changepoint.enabled and "changepoint" not in updated:
        updated.append("changepoint")
    return updated


def _signal_shap_top(
    shap_top: list[dict[str, Any]],
    mahalanobis: MahalanobisSignal,
    changepoint: ChangepointSignal,
) -> list[dict[str, Any]]:
    updated = list(shap_top)
    if mahalanobis.enabled:
        updated.append(
            {
                "feature": "mahalanobis_anomaly",
                "value": mahalanobis.probability,
                "shap": round(mahalanobis.probability * _weight(kya_settings.kya_w_mahalanobis), 8),
            }
        )
    if changepoint.enabled:
        updated.append(
            {
                "feature": "changepoint",
                "value": changepoint.changepoint_score,
                "shap": round(changepoint.changepoint_score * _weight(kya_settings.kya_w_changepoint), 8),
            }
        )
    return updated


def _weight(value: Any) -> float:
    try:
        return max(float(value), 0.0)
    except (TypeError, ValueError):
        return 0.0


def _confidence(result: EnsembleResult, baseline: dict[str, Any]) -> float:
    layer3_confidence = max(0.0, 1.0 - (result.confidence_high - result.confidence_low))
    baseline_confidence = float(baseline.get("confidence") or min(float(baseline.get("event_count") or 0) / 20, 1.0))
    return round(max(0.0, min(layer3_confidence * max(baseline_confidence, 0.05), 1.0)), 4)


async def _persist_agent_score(score: AgentTrustScore) -> None:
    pool = await db.get_pool()
    await pool.execute(
        """
        INSERT INTO agent_scores (agent_id, trust_score, risk_factors, shap_top, confidence)
        VALUES ($1, $2, $3::jsonb, $4::jsonb, $5)
        """,
        score.agent_id,
        score.trust_score,
        json.dumps(score.risk_factors),
        json.dumps(score.shap_top),
        score.confidence,
    )


async def _persist_cusum_state(agent_id: int, cusum_state: dict[str, Any]) -> None:
    pool = await db.get_pool()
    await pool.execute(
        """
        UPDATE agent_profiles
        SET baseline = jsonb_set(baseline, '{cusum_state}', $2::jsonb, true),
            updated_at = NOW()
        WHERE agent_id = $1
        """,
        agent_id,
        json.dumps(cusum_state, sort_keys=True),
    )


__all__ = [
    "AgentTrustScore",
    "CostReport",
    "CostTracker",
    "EnsembleResult",
    "Layer3MLEnsemble",
    "active_mode",
    "estimate_cost_usd",
    "reload_models",
    "score_agent_event",
    "score_transaction",
]
