import itertools
from typing import Any

import httpx

from backend.config import settings


class EthereumRPCClient:
    """Talosly blockchain data fetcher using JSON-RPC 2.0."""

    def __init__(self, rpc_url: str | None = None) -> None:
        self.rpc_url = rpc_url or settings.ethereum_rpc_url

    async def _call(self, method: str, params: list[Any]) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        # Production deployments should use HTTPS RPC endpoints.
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(self.rpc_url, json=payload)
            response.raise_for_status()
            data = response.json()
        if "error" in data:
            raise RuntimeError(f"Talosly RPC error: {data['error'].get('message', 'unknown error')}")
        return data["result"]

    async def get_latest_block_number(self) -> int:
        return int(await self._call("eth_blockNumber", []), 16)

    async def get_block_transactions(self, block_number: int) -> list[dict[str, Any]]:
        block = await self._call("eth_getBlockByNumber", [hex(block_number), True])
        return block.get("transactions", []) if block else []

    async def get_transactions_for_address(self, address: str, from_block: int, to_block: int) -> list[dict[str, Any]]:
        address_lower = address.lower()
        transactions: list[dict[str, Any]] = []
        for block_number in itertools.islice(range(from_block, to_block + 1), 5):
            for tx in await self.get_block_transactions(block_number):
                if (tx.get("to") or "").lower() == address_lower or (tx.get("from") or "").lower() == address_lower:
                    receipt = await self.get_transaction_receipt(tx["hash"])
                    tx["_receipt"] = receipt
                    transactions.append(tx)
        return transactions

    async def get_transaction_receipt(self, tx_hash: str) -> dict[str, Any]:
        return await self._call("eth_getTransactionReceipt", [tx_hash]) or {}

    def parse_transaction(self, raw_tx: dict[str, Any], receipt: dict[str, Any] | None = None) -> dict[str, Any]:
        receipt = receipt or raw_tx.get("_receipt") or {}
        value_wei = int(raw_tx.get("value") or "0x0", 16)
        gas_used = receipt.get("gasUsed") or raw_tx.get("gas")
        return {
            "tx_hash": raw_tx.get("hash"),
            "block_number": int(raw_tx.get("blockNumber") or "0x0", 16),
            "from_address": raw_tx.get("from"),
            "to_address": raw_tx.get("to"),
            "value_eth": value_wei / 10**18,
            "gas_used": int(gas_used, 16) if isinstance(gas_used, str) else gas_used,
            "input_data": (raw_tx.get("input") or "")[:500],
        }
