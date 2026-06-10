from fastapi.testclient import TestClient

from backend.main import app
from backend.middleware.auth import verify_api_key


def test_health_returns_talosly_status():
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "Talosly"}


def test_protocol_routes_are_disabled_by_default():
    response = TestClient(app).get("/api/protocols")

    assert response.status_code == 404


def test_protocol_create_route_is_disabled_by_default():
    response = TestClient(app).post("/api/protocols", json={"name": "Bad", "address": "0x123"})

    assert response.status_code == 404


def test_admin_endpoint_requires_secret():
    response = TestClient(app).get("/api/admin/metrics")
    assert response.status_code == 403


def test_dotenv_is_never_served_from_static_fallback():
    response = TestClient(app).get("/.env")

    assert response.status_code == 404
    assert "OPENAI_API_KEY" not in response.text


def test_encoded_dotenv_is_never_served_from_static_fallback():
    response = TestClient(app).get("/%2Eenv")

    assert response.status_code == 404
    assert "OPENAI_API_KEY" not in response.text


def test_alert_feedback_records_manual_review(monkeypatch):
    recorded = {}

    async def fake_submit_alert_feedback(alert_id, confirmed_threat, feedback_note):
        recorded.update(
            {
                "alert_id": alert_id,
                "confirmed_threat": confirmed_threat,
                "feedback_note": feedback_note,
            }
        )
        return True

    app.dependency_overrides[verify_api_key] = lambda: {"id": 1}
    monkeypatch.setattr("backend.database.submit_alert_feedback", fake_submit_alert_feedback)
    try:
        response = TestClient(app).post(
            "/api/alerts/42/feedback",
            json={"confirmed_threat": True, "feedback_note": "Confirmed exploit pattern"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "success", "message": "Feedback recorded for alert 42"}
    assert recorded == {
        "alert_id": 42,
        "confirmed_threat": True,
        "feedback_note": "Confirmed exploit pattern",
    }


def test_alert_feedback_patch_records_boolean_feedback(monkeypatch):
    recorded = {}

    async def fake_submit_alert_feedback(alert_id, confirmed_threat, feedback_note):
        recorded.update(
            {
                "alert_id": alert_id,
                "confirmed_threat": confirmed_threat,
                "feedback_note": feedback_note,
            }
        )
        return True

    app.dependency_overrides[verify_api_key] = lambda: {"id": 1}
    monkeypatch.setattr("backend.database.submit_alert_feedback", fake_submit_alert_feedback)
    try:
        response = TestClient(app).patch("/api/v1/alerts/42/feedback", json={"feedback": False})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "success", "message": "Feedback recorded for alert 42"}
    assert recorded == {
        "alert_id": 42,
        "confirmed_threat": False,
        "feedback_note": None,
    }


def test_alert_feedback_returns_404_for_missing_alert(monkeypatch):
    async def fake_submit_alert_feedback(_alert_id, _confirmed_threat, _feedback_note):
        return False

    app.dependency_overrides[verify_api_key] = lambda: {"id": 1}
    monkeypatch.setattr("backend.database.submit_alert_feedback", fake_submit_alert_feedback)
    try:
        response = TestClient(app).post("/api/alerts/404/feedback", json={"confirmed_threat": False})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


def test_alert_list_is_scoped_to_api_key(monkeypatch):
    captured = {}

    async def fake_get_alerts(limit, owner_api_key_id=None):
        captured.update({"limit": limit, "owner_api_key_id": owner_api_key_id})
        return []

    app.dependency_overrides[verify_api_key] = lambda: {"id": 11}
    monkeypatch.setattr("backend.database.get_alerts", fake_get_alerts)
    try:
        response = TestClient(app).get("/api/alerts?limit=25")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert captured == {"limit": 25, "owner_api_key_id": 11}


def test_transactions_route_is_disabled_by_default():
    response = TestClient(app).get("/api/transactions?protocol_id=99")

    assert response.status_code == 404
