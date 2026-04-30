import pytest

from backend.services.scorer import TransactionScorer


class TextBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class Message:
    def __init__(self, text):
        self.content = [TextBlock(text)]


class Messages:
    def __init__(self, text):
        self.text = text

    async def create(self, **_kwargs):
        return Message(self.text)


class FakeClient:
    def __init__(self, text):
        self.messages = Messages(text)


@pytest.mark.asyncio
async def test_json_response_parses_into_risk_score_response():
    scorer = TransactionScorer()
    scorer.client = FakeClient('{"risk_score": 87, "risk_summary": "Large suspicious call", "risk_factors": ["high value"]}')
    result = await scorer.score_transaction({"tx_hash": "0xabc", "input_data": "0x"}, {"name": "Talosly Test"})
    assert result.risk_score == 87
    assert result.risk_summary == "Large suspicious call"


@pytest.mark.asyncio
async def test_malformed_json_falls_back_to_score_50():
    scorer = TransactionScorer()
    scorer.client = FakeClient("not json")
    result = await scorer.score_transaction({"tx_hash": "0xabc", "input_data": "0x"}, {"name": "Talosly Test"})
    assert result.risk_score == 50
    assert result.risk_summary == "Scoring unavailable"


def test_out_of_range_score_raises_validation_error():
    scorer = TransactionScorer()
    with pytest.raises(ValueError):
        scorer._parse_response('{"risk_score": 150, "risk_summary": "Bad", "risk_factors": []}')
