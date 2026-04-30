import pytest

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
