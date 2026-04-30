from fastapi.testclient import TestClient

from backend.main import app


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
