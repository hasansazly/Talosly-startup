"""KYA trust scoring built on Talosly's existing Layer 3 machinery."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from backend import database as db
from kya.features import build_feature_vector
from kya.ingest import AgentEvent
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
    risk_probability = _kya_risk_probability(layer3_result, features)
    trust_score = int(round((1.0 - risk_probability) * 100))
    risk_factors = _risk_factors(features, layer3_result)
    shap_top = layer3_result.shap_top
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
    seq_anomaly = float(features.get("kya_sequence_anomaly") or 0.0)
    if seq_anomaly >= 0.5:
        deviation_risk += min(seq_anomaly * 0.30, 0.30)
    cp_prob = float(features.get("kya_bocpd_cp_prob") or 0.0)
    if cp_prob >= 0.3:
        deviation_risk += min(cp_prob * 0.40, 0.40)
    return min(max(result.ensemble_score, deviation_risk), 1.0)


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
    if float(features.get("kya_sequence_anomaly") or 0.0) >= 0.5:
        factors.append("sequence_break")
    if float(features.get("kya_bocpd_cp_prob") or 0.0) >= 0.7:
        factors.append("regime_change")
    for item in result.shap_top:
        feature = item.get("feature")
        if feature and feature not in factors and abs(float(item.get("shap") or 0.0)) > 0:
            factors.append(str(feature))
    return factors


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
