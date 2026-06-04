from fastapi.testclient import TestClient

from backend.main import app
from backend.middleware.auth import verify_api_key


class FakeTelegramService:
    def __init__(self, delivered: bool = True) -> None:
        self.delivered = delivered
        self.messages = []

    async def send_message(self, text, chat_id=None):
        self.messages.append({"text": text, "chat_id": chat_id})
        return self.delivered


def _with_key(key_id: int):
    app.dependency_overrides[verify_api_key] = lambda: {"id": key_id}


def test_owner_can_send_agent_test_alert(monkeypatch):
    sender = FakeTelegramService()

    async def fake_get_agent_for_owner(agent_id, owner_api_key_id):
        assert (agent_id, owner_api_key_id) == (7, 42)
        return {"id": 7, "name": "Treasury Agent"}

    monkeypatch.setattr("kya.api.db.get_agent_for_owner", fake_get_agent_for_owner)
    monkeypatch.setattr("kya.api.TelegramService", lambda: sender)
    _with_key(42)
    try:
        response = TestClient(app).post("/api/v1/agents/7/test-alert")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "message": "Test alert sent. Monitoring delivery confirmed.",
    }
    assert "Treasury Agent" in sender.messages[0]["text"]


def test_different_key_cannot_send_agent_test_alert(monkeypatch):
    sender = FakeTelegramService()

    async def fake_get_agent_for_owner(_agent_id, _owner_api_key_id):
        return None

    monkeypatch.setattr("kya.api.db.get_agent_for_owner", fake_get_agent_for_owner)
    monkeypatch.setattr("kya.api.TelegramService", lambda: sender)
    _with_key(99)
    try:
        response = TestClient(app).post("/api/v1/agents/7/test-alert")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert sender.messages == []


def test_agent_test_alert_reports_delivery_failure(monkeypatch):
    sender = FakeTelegramService(delivered=False)

    async def fake_get_agent_for_owner(_agent_id, _owner_api_key_id):
        return {"id": 7, "name": "Treasury Agent"}

    monkeypatch.setattr("kya.api.db.get_agent_for_owner", fake_get_agent_for_owner)
    monkeypatch.setattr("kya.api.TelegramService", lambda: sender)
    _with_key(42)
    try:
        response = TestClient(app).post("/api/v1/agents/7/test-alert")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "Test alert delivery failed"
