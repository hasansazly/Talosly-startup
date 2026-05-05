import pytest
from openai.resources.chat.completions import AsyncCompletions

from backend.config import settings
from backend.services.blacklist import BLACKLIST
from backend.services.scorer import TransactionScorer


class ChoiceMessage:
    def __init__(self, content):
        self.content = content


class Choice:
    def __init__(self, text):
        self.message = ChoiceMessage(text)


class Message:
    def __init__(self, text):
        self.choices = [Choice(text)]


@pytest.mark.asyncio
async def test_json_response_parses_into_risk_score_response(monkeypatch):
    async def fake_create(self, **kwargs):
        assert kwargs["model"] == "gpt-4o-mini"
        return Message('{"risk_score": 87, "risk_summary": "Large suspicious call", "risk_factors": ["high value"]}')

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_model", "gpt-4o-mini")
    monkeypatch.setattr(AsyncCompletions, "create", fake_create)
    scorer = TransactionScorer()
    result = await scorer.score_transaction({"tx_hash": "0xabc", "input_data": "0x"}, {"name": "Talosly Test"})
    assert result.risk_score == 87
    assert result.risk_summary == "Large suspicious call"


@pytest.mark.asyncio
async def test_new_security_prompt_response_parses_into_existing_api_shape(monkeypatch):
    async def fake_create(self, **kwargs):
        assert "Return ONLY this JSON" in kwargs["messages"][0]["content"]
        return Message('{"score": 72, "reason": "Approval exceeds safe threshold", "pattern": "APPROVAL", "action": "ALERT"}')

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(AsyncCompletions, "create", fake_create)
    scorer = TransactionScorer()
    result = await scorer.score_transaction({"tx_hash": "0xabc", "input_data": "0x"}, {"name": "Talosly Test"})
    assert result.risk_score == 72
    assert result.risk_summary == "Approval exceeds safe threshold"
    assert result.risk_factors == ["APPROVAL", "ALERT"]


@pytest.mark.asyncio
async def test_malformed_json_falls_back_to_score_50(monkeypatch):
    async def fake_create(self, **_kwargs):
        return Message("not json")

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(AsyncCompletions, "create", fake_create)
    scorer = TransactionScorer()
    result = await scorer.score_transaction({"tx_hash": "0xabc", "input_data": "0x"}, {"name": "Talosly Test"})
    assert result.risk_score == 50
    assert result.risk_summary == "Scoring unavailable"


def test_out_of_range_score_raises_validation_error():
    scorer = TransactionScorer()
    with pytest.raises(ValueError):
        scorer._parse_response('{"risk_score": 150, "risk_summary": "Bad", "risk_factors": []}')


def test_pre_screen_flags_blacklisted_address():
    scorer = TransactionScorer()
    result = scorer.pre_screen(
        {
            "tx_hash": "0xabc",
            "from_address": "0x0000000000000000000000000000000000000000",
            "to_address": next(iter(BLACKLIST)).upper(),
            "input_data": "0x",
            "value_eth": 0,
        }
    )
    assert result is not None
    assert result.risk_score == 98
    assert result.risk_factors == ["BLACKLISTED_ADDRESS"]


@pytest.mark.asyncio
async def test_score_transaction_runs_pre_screen_without_openai_key(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "")
    scorer = TransactionScorer()
    result = await scorer.score_transaction(
        {
            "tx_hash": "0xabc",
            "from_address": next(iter(BLACKLIST)).upper(),
            "to_address": "0x0000000000000000000000000000000000000000",
            "input_data": "0x",
            "value_eth": 0,
        },
        {"name": "Backtest"},
    )

    assert result.risk_score == 98
    assert result.risk_factors == ["BLACKLISTED_ADDRESS"]


def test_pre_screen_flags_self_transfer():
    scorer = TransactionScorer()
    result = scorer.pre_screen(
        {
            "tx_hash": "0xabc",
            "from_address": "0x1111111111111111111111111111111111111111",
            "to_address": "0x1111111111111111111111111111111111111111",
            "input_data": "0x",
            "value_eth": 0,
        }
    )
    assert result is not None
    assert result.risk_score == 78
    assert result.risk_summary == "Self-transfer detected"
    assert result.risk_factors == ["SELF_TRANSFER"]


def test_pre_screen_flags_zero_value_payload_probe_with_rpc_field_names():
    scorer = TransactionScorer()
    result = scorer.pre_screen(
        {
            "tx_hash": "0xabc",
            "from": "0x1111111111111111111111111111111111111111",
            "to": "0x2222222222222222222222222222222222222222",
            "input": "0x" + ("a" * 198),
            "value": "0x0",
        }
    )
    assert result is not None
    assert result.risk_score == 72
    assert result.risk_summary == "Zero value with large payload"
    assert result.risk_factors == ["PROBE_PATTERN"]
