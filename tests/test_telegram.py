from datetime import datetime, timedelta

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
    assert "Summary:" in message


def test_telegram_message_uses_safe_fallbacks_for_empty_values():
    service = TelegramService()
    message = service._format_message({}, {}, {"risk_score": None})

    assert "<b>Protocol:</b> Unknown Protocol" in message
    assert "<b>Risk Score:</b> <code>0/100</code>" in message
    assert "<b>View Tx:</b> No Hash Available" in message


def test_telegram_message_uses_explicit_newline_string_format():
    service = TelegramService()
    message = service._format_message(
        {"name": "Uniswap V3"},
        {"tx_hash": "0xabc123"},
        {"risk_score": 72, "risk_summary": "Suspicious high gas execution"},
    )

    assert message == (
        "🔴 <b>[CRITICAL THREAT]</b>\n"
        "<b>Protocol:</b> Uniswap V3\n"
        "<b>Risk Score:</b> <code>72/100</code>\n"
        "<b>Summary:</b> Suspicious high gas execution\n"
        "<b>View Tx:</b> https://etherscan.io/tx/0xabc123"
    )


def test_telegram_message_uses_warning_visual_for_medium_score():
    service = TelegramService()
    message = service._format_message({"name": "Aave"}, {"tx_hash": "0xabc"}, {"risk_score": 45})

    assert message.startswith("🟡 <b>[WARNING]</b>")


@pytest.mark.asyncio
async def test_should_send_alert_suppresses_recent_critical(monkeypatch):
    class FakePool:
        async def fetchrow(self, _query, _protocol_address):
            return {"created_at": datetime.utcnow() - timedelta(minutes=2), "risk_score": 98}

    async def fake_get_pool():
        return FakePool()

    monkeypatch.setattr("backend.services.telegram.db.get_pool", fake_get_pool)

    assert await TelegramService().should_send_alert("0xprotocol", "CRITICAL") is False


@pytest.mark.asyncio
async def test_should_send_alert_allows_warning_to_critical_escalation(monkeypatch):
    class FakePool:
        async def fetchrow(self, _query, _protocol_address):
            return {"created_at": datetime.utcnow() - timedelta(minutes=2), "risk_score": 45}

    async def fake_get_pool():
        return FakePool()

    monkeypatch.setattr("backend.services.telegram.db.get_pool", fake_get_pool)

    assert await TelegramService().should_send_alert("0xprotocol", "CRITICAL") is True


@pytest.mark.asyncio
async def test_telegram_send_suppressed_by_dedupe_does_not_post(monkeypatch):
    posts = []

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return None

        async def post(self, url, json):
            posts.append({"url": url, "json": json})
            raise AssertionError("Telegram should not be called when deduped")

    async def fake_should_send_alert(_protocol_address, _severity):
        return False

    monkeypatch.setattr(settings, "telegram_bot_token", "test-token")
    monkeypatch.setattr(settings, "telegram_chat_id", "123")
    monkeypatch.setattr("backend.services.telegram.httpx.AsyncClient", FakeClient)

    service = TelegramService()
    monkeypatch.setattr(service, "should_send_alert", fake_should_send_alert)

    result = await service.send_alert(
        {"name": "Uniswap V3", "address": "0xprotocol"},
        {"tx_hash": "0xabc"},
        {"risk_score": 98},
    )

    assert result is False
    assert service.last_send_suppressed is True
    assert posts == []


def test_telegram_plain_message_removes_html_tags_and_unescapes_values():
    service = TelegramService()
    message = service._format_message(
        {"name": 'Bad <Protocol> "Alpha"'},
        {"tx_hash": "0xabc<bad>&hash"},
        {"risk_score": 98},
    )

    assert service._format_plain_message(message) == (
        '🔴 [CRITICAL THREAT]\n'
        'Protocol: Bad <Protocol> "Alpha"\n'
        'Risk Score: 98/100\n'
        'Summary: No summary available\n'
        'View Tx: https://etherscan.io/tx/0xabc<bad>&hash'
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
        "🔴 [CRITICAL THREAT]\n"
        "Protocol: Uniswap V3\n"
        "Risk Score: 72/100\n"
        "Summary: No summary available\n"
        "View Tx: https://etherscan.io/tx/0xabc"
    )


def test_telegram_logs_specific_chat_not_found_message(caplog):
    class FakeResponse:
        status_code = 400
        text = '{"ok":false,"description":"Bad Request: chat not found"}'

    service = TelegramService()

    service._log_send_failure("HTML", FakeResponse())

    assert "chat not found" in caplog.text
    assert "TELEGRAM_CHAT_ID" in caplog.text
