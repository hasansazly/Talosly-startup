import json

import pytest

from kya.alerts import send_agent_score_alert
from kya.config import kya_settings
from kya.score import AgentTrustScore
from kya.signals.conformal import compute_conformal_signal


class FakeTelegramService:
    def __init__(self) -> None:
        self.calls = []

    async def send_smart_alert(self, protocol_data, score, tx_hash, reason=None):
        self.calls.append(
            {
                "protocol_data": protocol_data,
                "score": score,
                "tx_hash": tx_hash,
                "reason": reason,
            }
        )
        return True


class FakeProfilePool:
    def __init__(self) -> None:
        self.calibrations = []

    async def execute(self, _query, _agent_id, calibration_json):
        self.calibrations.append(json.loads(calibration_json))
        return "UPDATE 1"


def make_score(*, trust_score: int, isolation_score: float) -> AgentTrustScore:
    return AgentTrustScore(
        agent_id=7,
        trust_score=trust_score,
        risk_factors=["value_outlier"],
        shap_top=[{"feature": "pool_drain_ratio", "value": 1.0, "shap": 0.2}],
        confidence=0.91,
        layer3={"mode": "heuristic", "isolation_score": isolation_score},
    )


@pytest.fixture(autouse=True)
def conformal_config(monkeypatch):
    monkeypatch.setattr(kya_settings, "kya_enable_conformal", True)
    monkeypatch.setattr(kya_settings, "kya_conformal_alpha", 0.05)
    monkeypatch.setattr(kya_settings, "kya_conformal_window_size", 200)
    monkeypatch.setattr(kya_settings, "kya_conformal_min_samples", 4)
    monkeypatch.setattr(kya_settings, "kya_alert_threshold", 80)


def test_conformal_p_value_matches_known_calibration_set():
    signal = compute_conformal_signal(
        0.35,
        {"scores": [0.1, 0.2, 0.3, 0.4]},
    )

    assert signal.p_value == 0.4
    assert signal.confidence == 0.6
    assert signal.provisional is False
    assert signal.anomalous is False


@pytest.mark.asyncio
async def test_low_confidence_alert_is_suppressed_when_conformal_enabled(monkeypatch):
    pool = FakeProfilePool()
    sender = FakeTelegramService()

    async def fake_get_baseline(_agent_id):
        return {"conformal_calib": {"scores": [0.1, 0.2, 0.3, 0.4]}}

    async def fake_get_pool():
        return pool

    monkeypatch.setattr("kya.alerts.get_baseline", fake_get_baseline)
    monkeypatch.setattr("kya.alerts.db.get_pool", fake_get_pool)

    result = await send_agent_score_alert(
        {"name": "Treasury Agent", "principal_ref": "agent://treasury"},
        "0xhigh-legacy-risk",
        make_score(trust_score=5, isolation_score=0.2),
        telegram=sender,
    )

    assert result is False
    assert sender.calls == []
    assert pool.calibrations[-1]["sample_count"] == 5


@pytest.mark.asyncio
async def test_conformal_alert_includes_calibrated_confidence(monkeypatch):
    pool = FakeProfilePool()
    sender = FakeTelegramService()

    async def fake_get_baseline(_agent_id):
        return {"conformal_calib": {"scores": [0.1] * 20}}

    async def fake_get_pool():
        return pool

    monkeypatch.setattr("kya.alerts.get_baseline", fake_get_baseline)
    monkeypatch.setattr("kya.alerts.db.get_pool", fake_get_pool)

    result = await send_agent_score_alert(
        {"name": "Treasury Agent", "principal_ref": "agent://treasury"},
        "0xconformal-anomaly",
        make_score(trust_score=95, isolation_score=0.9),
        telegram=sender,
    )

    assert result is True
    assert "Conformal confidence: 95.2%." in sender.calls[0]["reason"]
    assert pool.calibrations[-1]["sample_count"] == 20


@pytest.mark.asyncio
async def test_existing_threshold_path_is_unchanged_when_conformal_disabled(monkeypatch):
    sender = FakeTelegramService()
    monkeypatch.setattr(kya_settings, "kya_enable_conformal", False)

    async def fail_get_baseline(_agent_id):
        raise AssertionError("flag-off alert path must not read conformal state")

    monkeypatch.setattr("kya.alerts.get_baseline", fail_get_baseline)

    result = await send_agent_score_alert(
        {"name": "Treasury Agent", "principal_ref": "agent://treasury"},
        "0xlegacy-alert",
        make_score(trust_score=5, isolation_score=0.2),
        telegram=sender,
    )

    assert result is True
    assert len(sender.calls) == 1
    assert "Conformal confidence" not in sender.calls[0]["reason"]
