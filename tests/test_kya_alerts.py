import pytest

from kya.alerts import send_agent_score_alert
from kya.score import AgentTrustScore


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


def make_score(*, trust_score: int, risk_factors: list[str] | None = None) -> AgentTrustScore:
    return AgentTrustScore(
        agent_id=7,
        trust_score=trust_score,
        risk_factors=risk_factors or [],
        shap_top=[
            {"feature": "pool_drain_ratio", "value": 1.0, "shap": 0.2},
            {"feature": "velocity", "value": 20.0, "shap": 0.12},
            {"feature": "gas_anomaly_zscore", "value": 50.0, "shap": 0.1},
        ],
        confidence=0.91,
        layer3={"mode": "heuristic"},
    )


@pytest.mark.asyncio
async def test_kya_alert_suppresses_scores_below_threshold(monkeypatch):
    monkeypatch.setattr("kya.alerts.kya_settings.kya_alert_threshold", 80)
    sender = FakeTelegramService()

    result = await send_agent_score_alert(
        {"name": "Treasury Agent", "principal_ref": "agent://treasury"},
        "0xnormal",
        make_score(trust_score=30),
        telegram=sender,
    )

    assert result is False
    assert sender.calls == []


@pytest.mark.asyncio
async def test_kya_alert_reuses_smart_telegram_sender_with_human_reasons(monkeypatch):
    monkeypatch.setattr("kya.alerts.kya_settings.kya_alert_threshold", 80)
    sender = FakeTelegramService()

    result = await send_agent_score_alert(
        {"name": "Treasury Agent", "principal_ref": "agent://treasury"},
        "0xdeviating-action",
        make_score(
            trust_score=5,
            risk_factors=["new_counterparty", "value_outlier", "cadence_break", "unseen_selector"],
        ),
        telegram=sender,
    )

    assert result is True
    assert len(sender.calls) == 1
    call = sender.calls[0]
    assert call["protocol_data"] == {
        "name": "KYA Agent: Treasury Agent",
        "address": "agent://treasury",
    }
    assert call["score"] == 95
    assert call["tx_hash"] == "0xdeviating-action"
    assert "Agent Treasury Agent action 0xdeviating-action scored 95/100 risk" in call["reason"]
    assert "funds to never-seen counterparty" in call["reason"]
    assert "value far above baseline" in call["reason"]
    assert "cadence break versus baseline" in call["reason"]
    assert "never-seen action selector" in call["reason"]
    assert "large value movement versus baseline" in call["reason"]
