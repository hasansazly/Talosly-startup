from scoring.hybrid_engine import HybridScoringEngine, bayesian_risk_update, combine_scores
from scoring.oracle_response import action_for_score


def _history(count: int = 80) -> list[dict]:
    return [
        {
            "tx_value": 1.0 + (index % 3) * 0.1,
            "gas_used": 21000 + (index % 5) * 100,
            "gas_price": 20 + (index % 4),
            "tx_frequency_1hr": 12,
            "tx_frequency_24hr": 240,
            "unique_counterparties": 20,
            "contract_age_days": 120,
            "timestamp": 1_700_000_000 + index * 60,
        }
        for index in range(count)
    ]


def test_hybrid_engine_skips_gpt_for_low_risk_transaction(tmp_path):
    engine = HybridScoringEngine(cost_tracker=None, ml_gate_threshold=65, confidence_gate=100)
    response = engine.score(
        _history()[-1],
        _history(),
        protocol_name="Test",
        protocol_address="0xtest",
        days_monitored=7,
    )

    assert 0 <= response.score <= 100
    assert response.gpt_consulted is False
    assert response.action in {"SAFE", "WARN", "ALERT", "PAUSE"}
    assert set(response.signals) == {"anomaly", "drain_velocity", "bayesian_deviation"}


def test_hybrid_engine_returns_oracle_schema_for_spike(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def fail_gpt(*_args, **_kwargs):
        raise RuntimeError("GPT disabled in test")

    monkeypatch.setattr(HybridScoringEngine, "_call_gpt", fail_gpt)
    engine = HybridScoringEngine(ml_gate_threshold=20, confidence_gate=0)
    tx = {
        **_history()[-1],
        "tx_value": 100,
        "gas_used": 500000,
        "tx_frequency_1hr": 900,
    }

    payload = engine.score(tx, _history(), protocol_name="Test", protocol_address="0xtest").to_dict()

    assert sorted(payload.keys())[:3] == ["action", "confidence", "gpt_consulted"]
    assert isinstance(payload["interval"], list)
    assert payload["gpt_consulted"] is True
    assert "warning" in payload


def test_bayesian_risk_and_action_boundaries():
    risk, deviation = bayesian_risk_update(
        {"tx_value": 50, "tx_frequency_1hr": 100},
        _history(),
    )

    assert 0 <= risk <= 1
    assert deviation > 0
    assert combine_scores(1.0, 1.0, 1.0) == 100
    assert action_for_score(39) == "SAFE"
    assert action_for_score(40) == "WARN"
    assert action_for_score(65) == "ALERT"
    assert action_for_score(86) == "PAUSE"
