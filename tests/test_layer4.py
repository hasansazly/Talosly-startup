import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from scoring.layer4 import Layer4Oracle, OracleResult


LAYER3_RESULT = {
    "ensemble_score": 0.87,
    "confidence_low": 0.81,
    "confidence_high": 0.93,
    "escalate_to_llm": True,
    "isolation_score": 0.72,
    "gbm_prob": 0.98,
    "bayesian_prob": 1.0,
    "shap_top": [
        {"feature": "flash_loan_fingerprint", "value": 1.0, "shap": 0.41},
        {"feature": "pool_drain_ratio", "value": 0.85, "shap": 0.28},
    ],
    "mode": "ml",
}

FEATURES = {
    "graph_centrality": 0.92,
    "velocity": 18.0,
    "pool_drain_ratio": 0.85,
    "flash_loan_fingerprint": 1.0,
    "wallet_age_days": 2.0,
    "tornado_tagged": True,
    "calldata_entropy": 6.81,
    "gas_anomaly_zscore": 42.0,
}

GOOD_RESPONSE = {
    "exploit_probability": 0.96,
    "confidence": "high",
    "verdict": "exploit",
    "reasoning": "Flash loan and pool drain signals are both extreme. Mixer funding and gas anomaly add supporting evidence.",
    "attack_type": "flash_loan",
    "sub_signals": [
        {
            "signal": "flash_loan_fingerprint",
            "value": 1.0,
            "risk_contribution": "high",
            "note": "Flash loan fingerprint is maximal.",
        }
    ],
    "recommended_action": "alert",
}


def _mock_response(content: str, prompt_tokens: int = 400, completion_tokens: int = 120):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


@pytest.mark.asyncio
async def test_layer4_valid_response_returns_oracle_result(tmp_path):
    oracle = Layer4Oracle(api_key="test-key", cost_log_file=tmp_path / "costs.jsonl")
    response = _mock_response(json.dumps(GOOD_RESPONSE))

    with patch.object(oracle._client.chat.completions, "create", new_callable=AsyncMock, return_value=response):
        result = await oracle.analyze("0xabc", FEATURES, LAYER3_RESULT)

    assert isinstance(result, OracleResult)
    assert result.verdict == "exploit"
    assert result.should_alert is True
    assert result.fallback_used is False
    assert result.layer3_score == LAYER3_RESULT["ensemble_score"]
    assert result.cost_usd > 0


@pytest.mark.asyncio
async def test_layer4_disabled_fails_open():
    oracle = Layer4Oracle(enabled=False)

    result = await oracle.analyze("0xabc", FEATURES, LAYER3_RESULT)

    assert result.fallback_used is True
    assert result.should_alert is True
    assert result.recommended_action == "alert"
    assert result.exploit_probability >= 0.60


@pytest.mark.asyncio
async def test_layer4_missing_api_key_fails_open(monkeypatch):
    monkeypatch.setattr("scoring.layer4.settings.openai_api_key", "")
    oracle = Layer4Oracle(api_key="")

    result = await oracle.analyze("0xabc", FEATURES, LAYER3_RESULT)

    assert result.fallback_used is True
    assert result.should_alert is True


@pytest.mark.asyncio
async def test_layer4_timeout_fails_open(tmp_path):
    oracle = Layer4Oracle(api_key="test-key", timeout_seconds=0.001, cost_log_file=tmp_path / "costs.jsonl")

    async def slow_call(*_args, **_kwargs):
        await asyncio.sleep(1)

    with patch.object(oracle._client.chat.completions, "create", new_callable=AsyncMock, side_effect=slow_call):
        result = await oracle.analyze("0xabc", FEATURES, LAYER3_RESULT)

    assert result.fallback_used is True
    assert result.should_alert is True


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["not json", "null", '{"exploit_probability": "yes"}'])
async def test_layer4_malformed_json_fails_open(tmp_path, raw):
    oracle = Layer4Oracle(api_key="test-key", cost_log_file=tmp_path / "costs.jsonl")
    response = _mock_response(raw)

    with patch.object(oracle._client.chat.completions, "create", new_callable=AsyncMock, return_value=response):
        result = await oracle.analyze("0xabc", FEATURES, LAYER3_RESULT)

    assert result.fallback_used is True
    assert result.should_alert is True


@pytest.mark.asyncio
async def test_layer4_probability_is_clamped(tmp_path):
    oracle = Layer4Oracle(api_key="test-key", cost_log_file=tmp_path / "costs.jsonl")
    response = _mock_response(json.dumps({**GOOD_RESPONSE, "exploit_probability": 2.5}))

    with patch.object(oracle._client.chat.completions, "create", new_callable=AsyncMock, return_value=response):
        result = await oracle.analyze("0xabc", FEATURES, LAYER3_RESULT)

    assert result.exploit_probability == 1.0


@pytest.mark.asyncio
async def test_layer4_logs_cost(tmp_path):
    cost_log = tmp_path / "layer4_costs.jsonl"
    oracle = Layer4Oracle(api_key="test-key", cost_log_file=cost_log)
    response = _mock_response(json.dumps(GOOD_RESPONSE), prompt_tokens=500, completion_tokens=200)

    with patch.object(oracle._client.chat.completions, "create", new_callable=AsyncMock, return_value=response):
        await oracle.analyze("0xabc", FEATURES, LAYER3_RESULT)

    rows = cost_log.read_text().splitlines()
    assert len(rows) == 1
    payload = json.loads(rows[0])
    assert payload["tx_hash"] == "0xabc"
    assert payload["cost_usd"] > 0
