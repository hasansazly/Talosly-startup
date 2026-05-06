import pytest

from backend.config import settings
from backend.services.etherscan import get_address_label


@pytest.mark.asyncio
async def test_get_address_label_returns_neutral_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "etherscan_api_key", "")

    assert await get_address_label("0x1111111111111111111111111111111111111111") == {
        "label": None,
        "is_dangerous": False,
    }


@pytest.mark.asyncio
async def test_get_address_label_marks_dangerous_contract_name(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"result": [{"ContractName": "Euler Finance Exploiter"}]}

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return None

        async def get(self, _url):
            return FakeResponse()

    monkeypatch.setattr(settings, "etherscan_api_key", "test-key")
    monkeypatch.setattr("backend.services.etherscan.httpx.AsyncClient", FakeClient)

    assert await get_address_label("0x1111111111111111111111111111111111111111") == {
        "label": "Euler Finance Exploiter",
        "is_dangerous": True,
    }
