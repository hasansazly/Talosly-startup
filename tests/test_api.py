from fastapi.testclient import TestClient

from backend.main import app


def test_health_returns_talosly_status():
    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"status": "ok", "service": "Talosly"}


def test_post_protocol_with_valid_address_succeeds():
    with TestClient(app) as client:
        response = client.post(
            "/api/protocols",
            json={"name": "Uniswap V3", "address": "0xE592427A0AEce92De3Edee1F18E0157C05861564"},
        )
        assert response.status_code == 201
        assert response.json()["name"] == "Uniswap V3"


def test_post_protocol_with_invalid_address_returns_422():
    with TestClient(app) as client:
        response = client.post("/api/protocols", json={"name": "Bad", "address": "0x123"})
        assert response.status_code == 422


def test_get_alerts_returns_list():
    with TestClient(app) as client:
        response = client.get("/api/alerts")
        assert response.status_code == 200
        assert response.json() == []
