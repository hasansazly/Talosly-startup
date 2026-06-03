from datetime import datetime, timezone

import pytest

from kya.ingest import AgentEvent, ingest_wallet


class FakeRPCClient:
    def __init__(self) -> None:
        self.requested_ranges = []

    async def get_latest_block_number(self) -> int:
        return 100

    async def get_transactions_for_address(self, address, from_block, to_block, block_transactions_cache=None):
        self.requested_ranges.append((address, from_block, to_block, block_transactions_cache))
        return [
            {
                "hash": "0xout",
                "blockNumber": "0x64",
                "from": address,
                "to": "0xcounterparty",
                "value": "0xde0b6b3a7640000",
                "input": "0x1234567890abcdef",
                "timestamp": "0x65",
            },
            {
                "hash": "0xin",
                "blockNumber": "0x64",
                "from": "0xsender",
                "to": address.upper(),
                "value": "0x0",
                "input": "0x",
                "timestamp": 102,
            },
        ]

    def parse_transaction(self, raw_tx, receipt=None):
        value_wei = int(raw_tx.get("value") or "0x0", 16)
        return {
            "tx_hash": raw_tx.get("hash"),
            "from_address": raw_tx.get("from"),
            "to_address": raw_tx.get("to"),
            "value_eth": value_wei / 10**18,
            "input_data": raw_tx.get("input") or "",
        }


@pytest.mark.asyncio
async def test_ingest_wallet_reads_recent_range_and_normalizes_events():
    client = FakeRPCClient()

    events = await ingest_wallet(7, "0xagent", 3, rpc_client=client)

    assert client.requested_ranges == [("0xagent", 98, 100, {})]
    assert events == [
        AgentEvent(
            tx_hash="0xout",
            agent_id=7,
            wallet="0xagent",
            counterparty="0xcounterparty",
            value=1.0,
            selector="12345678",
            timestamp=datetime.fromtimestamp(101, tz=timezone.utc),
            raw={
                "hash": "0xout",
                "blockNumber": "0x64",
                "from": "0xagent",
                "to": "0xcounterparty",
                "value": "0xde0b6b3a7640000",
                "input": "0x1234567890abcdef",
                "timestamp": "0x65",
            },
        ),
        AgentEvent(
            tx_hash="0xin",
            agent_id=7,
            wallet="0xagent",
            counterparty="0xsender",
            value=0.0,
            selector="",
            timestamp=datetime.fromtimestamp(102, tz=timezone.utc),
            raw={
                "hash": "0xin",
                "blockNumber": "0x64",
                "from": "0xsender",
                "to": "0XAGENT",
                "value": "0x0",
                "input": "0x",
                "timestamp": 102,
            },
        ),
    ]


@pytest.mark.asyncio
async def test_ingest_wallet_clamps_lookback_to_genesis():
    client = FakeRPCClient()

    await ingest_wallet(7, "0xagent", 500, rpc_client=client)

    assert client.requested_ranges[0][1:3] == (0, 100)
