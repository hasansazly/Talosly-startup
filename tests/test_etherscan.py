import pytest

from backend.config import settings
from backend.services.etherscan import get_address_label


@pytest.mark.asyncio
async def test_get_address_label_returns_neutral_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "etherscan_api_key", "")

    assert await get_address_label("0x1111111111111111111111111111111111111111") == {
        "label": None,
        "is_dangerous": False,
        "is_new_wallet": False,
        "funded_by_tornado": False,
        "tx_count": -1,
    }


@pytest.mark.asyncio
async def test_get_address_label_derives_v2_behavioral_signals(monkeypatch):
    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return None

        async def get(self, _url, params):
            self.calls += 1
            if params["module"] == "contract":
                return FakeResponse(
                    {"result": [{"ContractName": "", "ABI": "Contract source code not verified"}]}
                )
            return FakeResponse(
                {
                    "result": [
                        {"from": "0xd90e2f925da726b50c4ed8d0fb90ad053324f31b"},
                        {"from": "0x1111111111111111111111111111111111111111"},
                    ]
                }
            )

    monkeypatch.setattr(settings, "etherscan_api_key", "test-key")
    monkeypatch.setattr("backend.services.etherscan.httpx.AsyncClient", FakeClient)

    assert await get_address_label("0x1111111111111111111111111111111111111111") == {
        "label": "Tornado Cash funded, new wallet (2 txs), unverified contract",
        "is_dangerous": True,
        "is_new_wallet": True,
        "funded_by_tornado": True,
        "tx_count": 2,
    }
