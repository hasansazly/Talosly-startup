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
async def test_smart_alert_batches_recent_critical_by_editing_message(monkeypatch):
    posts = []
    saved = {}

    class FakeResponse:
        status_code = 200
        text = '{"ok":true,"result":{"message_id":123}}'
        is_success = True

        def json(self):
            return {"ok": True, "result": {"message_id": 123}}

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return None

        async def post(self, url, json):
            posts.append({"url": url, "json": json})
            return FakeResponse()

    monkeypatch.setattr(settings, "telegram_bot_token", "test-token")
    monkeypatch.setattr(settings, "telegram_chat_id", "123")
    monkeypatch.setattr("backend.services.telegram.httpx.AsyncClient", FakeClient)

    service = TelegramService()
    async def fake_state(_address):
        return {
            "last_alert_time": datetime.utcnow() - timedelta(minutes=2),
            "last_alert_message_id": 123,
            "alert_batch_count": 1,
            "last_alert_severity": "CRITICAL",
        }

    monkeypatch.setattr(service, "_get_protocol_alert_state", fake_state)

    async def fake_save(address, message_id, batch_count, severity, sent_at):
        saved.update(
            {
                "address": address,
                "message_id": message_id,
                "batch_count": batch_count,
                "severity": severity,
                "sent_at": sent_at,
            }
        )

    monkeypatch.setattr(service, "_save_protocol_alert_state", fake_save)

    result = await service.send_smart_alert(
        {"name": "Uniswap V3", "address": "0xprotocol"},
        98,
        "0xabc",
    )

    assert result is True
    assert len(posts) == 1
    assert "editMessageText" in posts[0]["url"]
    assert posts[0]["json"]["message_id"] == 123
    assert posts[0]["json"]["text"] == "🔴 [CRITICAL] 2 additional transactions detected! Status: Ongoing Attack. Latest Tx: 0xabc"
    assert saved["batch_count"] == 2
    assert saved["severity"] == "CRITICAL"


@pytest.mark.asyncio
async def test_smart_alert_sends_new_message_when_warning_escalates_to_critical(monkeypatch):
    posts = []
    saved = {}

    class FakeResponse:
        status_code = 200
        text = '{"ok":true,"result":{"message_id":456}}'
        is_success = True

        def json(self):
            return {"ok": True, "result": {"message_id": 456}}

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return None

        async def post(self, url, json):
            posts.append({"url": url, "json": json})
            return FakeResponse()

    monkeypatch.setattr(settings, "telegram_bot_token", "test-token")
    monkeypatch.setattr(settings, "telegram_chat_id", "123")
    monkeypatch.setattr("backend.services.telegram.httpx.AsyncClient", FakeClient)

    service = TelegramService()
    async def fake_state(_address):
        return {
            "last_alert_time": datetime.utcnow() - timedelta(minutes=2),
            "last_alert_message_id": 123,
            "alert_batch_count": 1,
            "last_alert_severity": "WARNING",
        }

    monkeypatch.setattr(service, "_get_protocol_alert_state", fake_state)

    async def fake_save(address, message_id, batch_count, severity, sent_at):
        saved.update({"address": address, "message_id": message_id, "batch_count": batch_count, "severity": severity})

    monkeypatch.setattr(service, "_save_protocol_alert_state", fake_save)

    result = await service.send_smart_alert({"name": "Aave", "address": "0xprotocol"}, 98, "0xabc")

    assert result is True
    assert len(posts) == 1
    assert "sendMessage" in posts[0]["url"]
    assert "editMessageText" not in posts[0]["url"]
    assert saved["message_id"] == 456
    assert saved["batch_count"] == 1
    assert saved["severity"] == "CRITICAL"


@pytest.mark.asyncio
async def test_smart_alert_sends_new_message_when_old_message_cannot_be_edited(monkeypatch):
    posts = []
    saved = {}

    class FakeResponse:
        def __init__(self, status_code, message_id=None):
            self.status_code = status_code
            self.text = '{"ok":true}' if status_code < 400 else '{"ok":false}'
            self.is_success = status_code < 400
            self.message_id = message_id

        def json(self):
            return {"ok": self.is_success, "result": {"message_id": self.message_id}}

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return None

        async def post(self, url, json):
            posts.append({"url": url, "json": json})
            if "editMessageText" in url:
                return FakeResponse(400)
            return FakeResponse(200, 999)

    monkeypatch.setattr(settings, "telegram_bot_token", "test-token")
    monkeypatch.setattr(settings, "telegram_chat_id", "123")
    monkeypatch.setattr("backend.services.telegram.httpx.AsyncClient", FakeClient)

    service = TelegramService()
    async def fake_state(_address):
        return {
            "last_alert_time": datetime.utcnow() - timedelta(minutes=2),
            "last_alert_message_id": 123,
            "alert_batch_count": 3,
            "last_alert_severity": "CRITICAL",
        }

    monkeypatch.setattr(service, "_get_protocol_alert_state", fake_state)

    async def fake_save(address, message_id, batch_count, severity, sent_at):
        saved.update({"address": address, "message_id": message_id, "batch_count": batch_count, "severity": severity})

    monkeypatch.setattr(service, "_save_protocol_alert_state", fake_save)

    result = await service.send_smart_alert({"name": "Aave", "address": "0xprotocol"}, 98, "0xabc")

    assert result is True
    assert len(posts) == 2
    assert "editMessageText" in posts[0]["url"]
    assert "sendMessage" in posts[1]["url"]
    assert saved["message_id"] == 999
    assert saved["batch_count"] == 1


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

        def json(self):
            return {"ok": self.is_success, "result": {"message_id": 321}}

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
