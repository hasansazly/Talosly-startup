from copy import deepcopy
from datetime import datetime, timezone

import asyncpg
from fastapi.testclient import TestClient

from backend.main import app
from backend.middleware.auth import verify_api_key


def _with_key(key_id: int):
    app.dependency_overrides[verify_api_key] = lambda: {"id": key_id}


def test_owner_reads_own_agent_score(monkeypatch):
    computed_at = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)

    async def fake_get_agent_score_for_owner(agent_id, owner_api_key_id):
        assert (agent_id, owner_api_key_id) == (7, 42)
        return {
            "id": 99,
            "agent_id": 7,
            "trust_score": 88,
            "risk_factors": [],
            "shap_top": [],
            "confidence": 0.9,
            "computed_at": computed_at,
        }

    monkeypatch.setattr("kya.api.db.get_agent_score_for_owner", fake_get_agent_score_for_owner)
    _with_key(42)
    try:
        response = TestClient(app).get("/api/v1/agents/7/score")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["agent_id"] == 7


def test_different_key_cannot_read_or_score_agent(monkeypatch):
    async def fake_get_agent_score_for_owner(_agent_id, _owner_api_key_id):
        return None

    async def fake_get_agent_for_owner(_agent_id, _owner_api_key_id):
        return None

    monkeypatch.setattr("kya.api.db.get_agent_score_for_owner", fake_get_agent_score_for_owner)
    monkeypatch.setattr("kya.api.db.get_agent_for_owner", fake_get_agent_for_owner)
    _with_key(99)
    try:
        score_response = TestClient(app).get("/api/v1/agents/7/score")
        action_response = TestClient(app).post(
            "/api/v1/agent-score",
            json={"agent_id": 7, "wallet": "0xagent", "action": "0xaction"},
        )
    finally:
        app.dependency_overrides.clear()

    assert score_response.status_code == 404
    assert action_response.status_code == 404
    assert action_response.json()["detail"]["error"] == "Agent not found"


def test_duplicate_wallet_leaves_no_orphan_agent(monkeypatch):
    state = {
        "agents": [],
        "wallets": [{"agent_id": 1, "address": "0xduplicate"}],
    }

    class FakeTransaction:
        def __init__(self):
            self.snapshot = None

        async def __aenter__(self):
            self.snapshot = deepcopy(state)
            return self

        async def __aexit__(self, exc_type, _exc, _traceback):
            if exc_type is not None:
                state.clear()
                state.update(self.snapshot)
            return False

    class FakeConnection:
        def transaction(self):
            return FakeTransaction()

        async def fetchval(self, query, *args):
            if "INSERT INTO agents" in query:
                agent_id = len(state["agents"]) + 2
                state["agents"].append({"id": agent_id, "owner_api_key_id": args[3]})
                return agent_id
            if any(wallet["address"] == args[2] for wallet in state["wallets"]):
                raise asyncpg.UniqueViolationError("duplicate wallet")
            state["wallets"].append({"agent_id": args[0], "address": args[2]})
            return len(state["wallets"])

    class FakeAcquire:
        async def __aenter__(self):
            return FakeConnection()

        async def __aexit__(self, _exc_type, _exc, _traceback):
            return False

    class FakePool:
        def acquire(self):
            return FakeAcquire()

    async def fake_get_pool():
        return FakePool()

    monkeypatch.setattr("kya.api.db.get_pool", fake_get_pool)
    _with_key(42)
    try:
        response = TestClient(app).post(
            "/api/v1/agents",
            json={
                "name": "Duplicate Agent",
                "principal_ref": "agent://duplicate",
                "wallet_address": "0xduplicate",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert state["agents"] == []


def test_list_returns_only_requesting_keys_agents(monkeypatch):
    async def fake_get_agents_for_owner(owner_api_key_id):
        assert owner_api_key_id == 42
        return [
            {
                "id": 7,
                "name": "Owned Agent",
                "principal_ref": "agent://owned",
                "status": "active",
                "owner_api_key_id": 42,
                "wallet": {"id": 11, "agent_id": 7, "chain": "ethereum", "address": "0xowned"},
                "latest_score": {"trust_score": 91},
            }
        ]

    monkeypatch.setattr("kya.api.db.get_agents_for_owner", fake_get_agents_for_owner)
    _with_key(42)
    try:
        response = TestClient(app).get("/api/v1/agents")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert [agent["id"] for agent in response.json()] == [7]
    assert response.json()[0]["latest_score"]["trust_score"] == 91
