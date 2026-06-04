from fastapi.testclient import TestClient

from backend.main import app
from backend.middleware.auth import verify_api_key

ETHEREUM_WALLET = "0x1111111111111111111111111111111111111111"
BASE_WALLET = "0xabcdefABCDEFabcdefABCDEFabcdefABCDEFabcd"


class FakeConnection:
    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback):
        return False

    async def fetchval(self, query, *_args):
        return 7 if "INSERT INTO agents" in query else 11


class FakePool:
    def acquire(self):
        return FakeConnection()


def _register(monkeypatch, *, wallet_address: str, chain: str):
    async def fake_get_pool():
        return FakePool()

    monkeypatch.setattr("kya.api.db.get_pool", fake_get_pool)
    app.dependency_overrides[verify_api_key] = lambda: {"id": 42}
    try:
        return TestClient(app).post(
            "/api/v1/agents",
            json={
                "name": "Validated Agent",
                "principal_ref": "agent://validated",
                "wallet_address": wallet_address,
                "chain": chain,
            },
        )
    finally:
        app.dependency_overrides.clear()


def test_register_agent_accepts_valid_evm_addresses(monkeypatch):
    ethereum_response = _register(monkeypatch, wallet_address=ETHEREUM_WALLET, chain="ethereum")
    base_response = _register(monkeypatch, wallet_address=BASE_WALLET, chain="base")

    assert ethereum_response.status_code == 201
    assert ethereum_response.json()["wallet"]["address"] == ETHEREUM_WALLET
    assert base_response.status_code == 201
    assert base_response.json()["wallet"]["chain"] == "base"


def test_register_agent_rejects_invalid_wallet_address(monkeypatch):
    response = _register(monkeypatch, wallet_address="0xagent", chain="ethereum")

    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "Invalid wallet address"
    assert "40 hexadecimal characters" in response.json()["detail"]["detail"]


def test_register_agent_rejects_unsupported_chain(monkeypatch):
    response = _register(monkeypatch, wallet_address=ETHEREUM_WALLET, chain="solana")

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "error": "Unsupported chain",
        "detail": "Supported chains: base, ethereum",
    }
