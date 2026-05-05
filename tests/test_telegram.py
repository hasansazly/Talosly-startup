import pytest

from backend.config import settings
from backend.services.telegram import TelegramService


def test_telegram_message_escapes_dynamic_values_before_html_formatting():
    service = TelegramService()
    message = service._format_message(
        {"name": 'Bad <Protocol> "Alpha"'},
        {"tx_hash": "0xabc<bad>&hash"},
        {"risk_score": 98},
    )

    assert "Bad &lt;Protocol&gt; &quot;Alpha&quot;" in message
    assert "0xabc&lt;bad&gt;&amp;hash" in message
    assert "Bad <Protocol>" not in message
    assert "0xabc<bad>&hash" not in message


def test_telegram_message_uses_safe_fallbacks_for_empty_values():
    service = TelegramService()
    message = service._format_message({}, {}, {"risk_score": None})

    assert "<b>Protocol:</b> Unknown Protocol" in message
    assert "<b>Score:</b> <code>0</code>" in message
    assert "<b>TX:</b> <code>No Hash Available</code>" in message


def test_telegram_message_uses_explicit_newline_string_format():
    service = TelegramService()
    message = service._format_message({"name": "Uniswap V3"}, {"tx_hash": "0xabc123"}, {"risk_score": 72})

    assert message == (
        "🚨 <b>New Risk Alert</b> 🚨\n"
        "<b>Protocol:</b> Uniswap V3\n"
        "<b>Score:</b> <code>72</code>\n"
        "<b>TX:</b> <code>0xabc123</code>"
    )


def test_telegram_plain_message_removes_html_tags_and_unescapes_values():
    service = TelegramService()
    message = service._format_message(
        {"name": 'Bad <Protocol> "Alpha"'},
        {"tx_hash": "0xabc<bad>&hash"},
        {"risk_score": 98},
    )

    assert service._format_plain_message(message) == (
        '🚨 New Risk Alert 🚨\n'
        'Protocol: Bad <Protocol> "Alpha"\n'
        'Score: 98\n'
        'TX: 0xabc<bad>&hash'
    )


@pytest.mark.asyncio
async def test_telegram_send_retries_without_parse_mode_after_html_400(monkeypatch):
    posts = []

    class FakeResponse:
        def __init__(self, status_code, text):
            self.status_code = status_code
            self.text = text
            self.is_success = status_code < 400

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return None

        async def post(self, url, json):
            posts.append({"url": url, "json": json})
            if len(posts) == 1:
                return FakeResponse(400, '{"ok":false,"description":"Bad Request"}')
            return FakeResponse(200, '{"ok":true}')

    monkeypatch.setattr(settings, "telegram_bot_token", "test-token")
    monkeypatch.setattr(settings, "telegram_chat_id", "123")
    monkeypatch.setattr("backend.services.telegram.httpx.AsyncClient", FakeClient)

    result = await TelegramService().send_alert({"name": "Uniswap V3"}, {"tx_hash": "0xabc"}, {"risk_score": 72})

    assert result is True
    assert posts[0]["json"]["parse_mode"] == "HTML"
    assert "parse_mode" not in posts[1]["json"]
    assert posts[1]["json"]["text"] == (
        "🚨 New Risk Alert 🚨\n"
        "Protocol: Uniswap V3\n"
        "Score: 72\n"
        "TX: 0xabc"
    )
