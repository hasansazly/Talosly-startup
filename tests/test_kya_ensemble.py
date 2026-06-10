from datetime import datetime, timezone
import json

import pytest

from kya.config import kya_settings
from kya.ingest import AgentEvent
from kya.score import score_agent_event
from scoring.layer3 import EnsembleResult


FEATURES = {"x": 5.0, "y": 5.0}


class FixedLayer3:
    def __init__(self, isolation_score: float = 0.1) -> None:
        self.result = EnsembleResult(
            tx_hash="0xevent",
            ensemble_score=0.1,
            confidence_low=0.05,
            confidence_high=0.15,
            escalate_to_llm=False,
            isolation_score=isolation_score,
            gbm_prob=0.1,
            bayesian_prob=0.1,
            shap_top=[{"feature": "velocity", "value": 0.1, "shap": 0.02}],
            latency_ms=1.0,
            mode="heuristic",
        )

    def score(self, _tx_hash, _features):
        return self.result


class FakeScorePool:
    def __init__(self) -> None:
        self.scores = []
        self.cusum_states = []

    async def execute(self, query, *args):
        if "INSERT INTO agent_scores" in query:
            agent_id, trust_score, risk_factors_json, shap_top_json, confidence = args
            self.scores.append(
                {
                    "agent_id": agent_id,
                    "trust_score": trust_score,
                    "risk_factors": json.loads(risk_factors_json),
                    "shap_top": json.loads(shap_top_json),
                    "confidence": confidence,
                }
            )
        elif "UPDATE agent_profiles" in query:
            self.cusum_states.append(json.loads(args[1]))
        return "OK"


@pytest.fixture(autouse=True)
def ensemble_config(monkeypatch):
    monkeypatch.delenv("KYA_ENABLE_MAHALANOBIS", raising=False)
    monkeypatch.setattr(kya_settings, "kya_enable_mahalanobis", False)
    monkeypatch.setattr(kya_settings, "kya_enable_changepoint", False)
    monkeypatch.setattr(kya_settings, "kya_enable_conformal", False)
    monkeypatch.setattr(kya_settings, "kya_cusum_drift", 0.01)
    monkeypatch.setattr(kya_settings, "kya_cusum_threshold", 0.25)
    monkeypatch.setattr(kya_settings, "kya_w_base", 1.0)
    monkeypatch.setattr(kya_settings, "kya_w_mahalanobis", 1.0)
    monkeypatch.setattr(kya_settings, "kya_w_changepoint", 1.0)
    monkeypatch.setattr("kya.score.build_feature_vector", lambda _event, _baseline: FEATURES)


@pytest.fixture
def score_pool(monkeypatch):
    pool = FakeScorePool()

    async def fake_get_pool():
        return pool

    monkeypatch.setattr("kya.score.db.get_pool", fake_get_pool)
    return pool


def event() -> AgentEvent:
    return AgentEvent(
        tx_hash="0xevent",
        agent_id=1,
        wallet="0xagent",
        counterparty="0xknown",
        value=1.0,
        selector="abcdef12",
        timestamp=datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
        raw={"hash": "0xevent"},
    )


def baseline() -> dict:
    return {
        "event_count": 20,
        "confidence": 1.0,
        "known_counterparties": ["0xknown"],
        "selectors_seen": ["abcdef12"],
        "active_hours": {"12": 20},
        "value_stats": {"count": 20, "mean": 1.0, "std": 0.1},
        "cadence_stats": {"count": 0},
        "robust_stats": {
            "feature_names": ["x", "y"],
            "median": [0.0, 0.0],
            "mad": [1.0, 1.0],
            "covariance": [[1.0, 0.9], [0.9, 1.0]],
            "low_confidence": False,
        },
        "cusum_state": {
            "s_high": 0.0,
            "s_low": 0.0,
            "reference_mean": 0.1,
            "count": 10,
        },
    }


def mature_signal_baseline() -> dict:
    data = baseline()
    data["event_count"] = 30
    data["cusum_state"]["count"] = 30
    return data


@pytest.mark.asyncio
async def test_flags_off_output_is_bit_identical_to_pre_change_score(score_pool):
    score = await score_agent_event(1, event(), mature_signal_baseline(), layer3=FixedLayer3())

    assert score.to_dict() == {
        "agent_id": 1,
        "trust_score": 90,
        "risk_factors": ["velocity"],
        "shap_top": [{"feature": "velocity", "value": 0.1, "shap": 0.02}],
        "confidence": 0.9,
        "layer3": FixedLayer3().result.to_dict(),
    }
    assert score_pool.cusum_states == []


@pytest.mark.asyncio
async def test_mahalanobis_spike_raises_risk_and_is_explained(score_pool, monkeypatch):
    monkeypatch.setenv("KYA_ENABLE_MAHALANOBIS", "true")
    monkeypatch.setattr(kya_settings, "kya_enable_mahalanobis", True)
    monkeypatch.setattr(kya_settings, "kya_w_mahalanobis", 3.0)

    score = await score_agent_event(1, event(), mature_signal_baseline(), layer3=FixedLayer3())

    assert score.trust_score < 90
    assert "mahalanobis_anomaly" in score.risk_factors
    assert any(item["feature"] == "mahalanobis_anomaly" for item in score.shap_top)


@pytest.mark.asyncio
async def test_changepoint_spike_raises_risk_and_is_explained(score_pool, monkeypatch):
    monkeypatch.setattr(kya_settings, "kya_enable_changepoint", True)
    shifted = mature_signal_baseline()
    shifted["cusum_state"]["s_high"] = 0.24

    score = await score_agent_event(1, event(), shifted, layer3=FixedLayer3(isolation_score=0.3))

    assert score.trust_score < 70
    assert "changepoint" in score.risk_factors
    assert any(item["feature"] == "changepoint" for item in score.shap_top)
    assert score_pool.cusum_states[-1]["s_high"] == 0.0
