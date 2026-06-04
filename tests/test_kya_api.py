from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.main import app
from backend.middleware.auth import verify_api_key

VALID_WALLET = "0x1111111111111111111111111111111111111111"


def test_kya_register_agent_requires_api_key():
    response = TestClient(app).post(
        "/api/v1/agents",
        json={
            "name": "Treasury Agent",
            "principal_ref": "agent://treasury",
            "wallet_address": VALID_WALLET,
        },
    )

    assert response.status_code == 403


def test_kya_register_agent_connects_wallet(monkeypatch):
    captured = []

    class FakeConnection:
        async def fetchval(self, query, *args):
            captured.append({"query": query, "args": args})
            return 7 if "INSERT INTO agents" in query else 11

        def transaction(self):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _traceback):
            return False

    class FakePool:
        def acquire(self):
            return FakeConnection()

    async def fake_get_pool():
        return FakePool()

    app.dependency_overrides[verify_api_key] = lambda: {"id": 42}
    monkeypatch.setattr("kya.api.db.get_pool", fake_get_pool)
    try:
        response = TestClient(app).post(
            "/api/v1/agents",
            json={
                "name": "Treasury Agent",
                "principal_ref": "agent://treasury",
                "wallet_address": VALID_WALLET,
                "chain": "ethereum",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["id"] == 7
    assert response.json()["wallet"] == {
        "id": 11,
        "agent_id": 7,
        "chain": "ethereum",
        "address": VALID_WALLET,
    }
    assert captured[0]["args"] == ("Treasury Agent", "agent://treasury", "active", 42)
    assert captured[1]["args"] == (7, "ethereum", VALID_WALLET)


def test_kya_get_agent_score_returns_latest_score(monkeypatch):
    computed_at = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)

    async def fake_get_agent_score_for_owner(agent_id, owner_api_key_id):
        assert (agent_id, owner_api_key_id) == (7, 42)
        return {
            "id": 99,
            "agent_id": 7,
            "trust_score": 21,
            "risk_factors": ["new_counterparty"],
            "shap_top": [{"feature": "velocity", "shap": 0.12}],
            "confidence": 0.8,
            "computed_at": computed_at,
        }

    app.dependency_overrides[verify_api_key] = lambda: {"id": 42}
    monkeypatch.setattr("kya.api.db.get_agent_score_for_owner", fake_get_agent_score_for_owner)
    try:
        response = TestClient(app).get("/api/v1/agents/7/score")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "id": 99,
        "agent_id": 7,
        "trust_score": 21,
        "risk_factors": ["new_counterparty"],
        "shap_top": [{"feature": "velocity", "shap": 0.12}],
        "confidence": 0.8,
        "computed_at": "2026-01-01T12:00:00+00:00",
    }


def test_kya_agent_score_is_disabled_by_default(monkeypatch):
    async def fake_get_agent_for_owner(_agent_id, _owner_api_key_id):
        return {"id": 7}

    app.dependency_overrides[verify_api_key] = lambda: {"id": 42}
    monkeypatch.setattr("kya.api.db.get_agent_for_owner", fake_get_agent_for_owner)
    try:
        response = TestClient(app).post(
            "/api/v1/agent-score",
            json={
                "agent_id": 7,
                "wallet": "0xagent",
                "action": "0xaction",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "KYA disabled"


def test_kya_agent_score_scores_supplied_action_when_enabled(monkeypatch):
    persisted = []

    class FakePool:
        async def execute(self, _query, agent_id, trust_score, risk_factors, shap_top, confidence):
            persisted.append(
                {
                    "agent_id": agent_id,
                    "trust_score": trust_score,
                    "risk_factors": risk_factors,
                    "shap_top": shap_top,
                    "confidence": confidence,
                }
            )
            return "INSERT 0 1"

    async def fake_get_pool():
        return FakePool()

    async def fake_get_agent_for_owner(_agent_id, _owner_api_key_id):
        return {"id": 7}

    app.dependency_overrides[verify_api_key] = lambda: {"id": 42}
    monkeypatch.setattr("kya.api.kya_settings.enable_kya", True)
    monkeypatch.setattr("kya.api.db.get_agent_for_owner", fake_get_agent_for_owner)
    monkeypatch.setattr("kya.score.db.get_pool", fake_get_pool)
    try:
        response = TestClient(app).post(
            "/api/v1/agent-score",
            json={
                "agent_id": 7,
                "wallet": "0xagent",
                "action": "0xdeviating-action",
                "counterparty": "0xnew",
                "value": 50.0,
                "selector": "deadbeef",
                "timestamp": "2026-01-01T14:00:00Z",
                "raw": {
                    "input": "0xdeadbeef",
                    "sender_first_seen_ts": 1767272400,
                    "tornado_tagged": True,
                },
                "baseline": {
                    "event_count": 25,
                    "confidence": 1.0,
                    "known_counterparties": ["0xknown"],
                    "selectors_seen": ["abcdef12"],
                    "active_hours": {"12": 25},
                    "value_stats": {"count": 25, "mean": 1.0, "std": 0.1},
                    "cadence_stats": {
                        "count": 12,
                        "mean_seconds": 600.0,
                        "std_seconds": 30.0,
                        "last_timestamp": "2026-01-01T12:00:00+00:00",
                    },
                },
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["agent_id"] == 7
    assert body["action"] == "0xdeviating-action"
    assert body["trust_score"] <= 40
    assert {"new_counterparty", "unseen_selector", "value_outlier"} <= set(body["risk_factors"])
    assert len(body["shap_top"]) == 3
    assert body["features"]["kya_new_counterparty"] is True
    assert persisted
