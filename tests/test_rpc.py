import pytest
import httpx

from backend.config import settings
from backend.services.rpc import EthereumRPCClient


@pytest.mark.asyncio
async def test_get_latest_block_number_parses_hex(monkeypatch):
    client = EthereumRPCClient()

    async def fake_call(method, params):
        assert method == "eth_blockNumber"
        return "0x10"

    monkeypatch.setattr(client, "_call", fake_call)
    assert await client.get_latest_block_number() == 16


def test_parse_transaction_converts_hex_wei_to_eth():
    client = EthereumRPCClient()
    parsed = client.parse_transaction(
        {
            "hash": "0xabc",
            "blockNumber": "0x1",
            "from": "0xfrom",
            "to": "0xto",
            "value": "0xde0b6b3a7640000",
            "input": "0x1234",
        },
        {"gasUsed": "0x5208"},
    )
    assert parsed["value_eth"] == 1
    assert parsed["gas_used"] == 21000


def test_parse_transaction_truncates_input_data():
    client = EthereumRPCClient()
    parsed = client.parse_transaction(
        {
            "hash": "0xabc",
            "blockNumber": "0x1",
            "from": "0xfrom",
            "to": "0xto",
            "value": "0x0",
            "input": "0x" + "a" * 600,
        }
    )
    assert len(parsed["input_data"]) == 500


def test_parse_transaction_preserves_receipt_logs_for_scorer_context():
    client = EthereumRPCClient()
    parsed = client.parse_transaction(
        {
            "hash": "0xabc",
            "blockNumber": "0x1",
            "from": "0xfrom",
            "to": "0xto",
            "value": "0x0",
            "input": "0x1234",
        },
        {"gasUsed": "0x5208", "logs": [{"address": "0xlog", "topics": ["0xtopic"], "data": "0x1"}]},
    )

    assert parsed["logs"] == [{"address": "0xlog", "topics": ["0xtopic"], "data": "0x1"}]


@pytest.mark.asyncio
async def test_get_transactions_for_address_reuses_block_cache(monkeypatch):
    client = EthereumRPCClient()
    block_calls = 0
    receipt_calls = 0

    async def fake_get_block_transactions(block_number):
        nonlocal block_calls
        block_calls += 1
        return [
            {
                "hash": f"0x{block_number}",
                "blockNumber": hex(block_number),
                "from": "0xfrom",
                "to": "0xtarget",
                "value": "0x0",
            }
        ]

    async def fake_get_transaction_receipt(tx_hash):
        nonlocal receipt_calls
        receipt_calls += 1
        return {"status": "0x1"}

    monkeypatch.setattr(client, "get_block_transactions", fake_get_block_transactions)
    monkeypatch.setattr(client, "get_transaction_receipt", fake_get_transaction_receipt)

    cache = {}
    first = await client.get_transactions_for_address("0xtarget", 10, 10, cache)
    second = await client.get_transactions_for_address("0xtarget", 10, 10, cache)

    assert first[0]["hash"] == "0x10"
    assert second[0]["hash"] == "0x10"
    assert block_calls == 1
    assert receipt_calls == 2


@pytest.mark.asyncio
async def test_call_retries_429(monkeypatch):
    client = EthereumRPCClient("https://example.test")
    monkeypatch.setattr(settings, "ethereum_rpc_min_interval_seconds", 0)
    monkeypatch.setattr(settings, "ethereum_rpc_max_retries", 1)

    responses = [
        httpx.Response(429, json={"error": "slow down"}, headers={"retry-after": "0"}),
        httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x10"}),
    ]

    async def handler(request):
        return responses.pop(0)

    original_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda timeout: original_async_client(transport=httpx.MockTransport(handler), timeout=timeout),
    )

    assert await client._call("eth_blockNumber", []) == "0x10"
