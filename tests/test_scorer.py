import pytest
from openai.resources.chat.completions import AsyncCompletions

from backend.config import settings
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
