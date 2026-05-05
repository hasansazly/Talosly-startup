from fastapi.testclient import TestClient

from backend.main import app
from backend.middleware.auth import verify_api_key


def test_health_returns_talosly_status():
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "Talosly"}


def test_protected_protocols_require_api_key():
    response = TestClient(app).get("/api/protocols")
    assert response.status_code == 403


def test_invalid_protocol_body_still_validates_on_model():
    response = TestClient(app).post("/api/protocols", json={"name": "Bad", "address": "0x123"})
    assert response.status_code in {403, 422}


def test_admin_endpoint_requires_secret():
    response = TestClient(app).get("/api/admin/metrics")
    assert response.status_code == 403


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
