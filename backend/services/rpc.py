import asyncio
import contextlib
import itertools
from typing import Any

import httpx

from backend.config import settings


class EthereumRPCRateLimitError(RuntimeError):
    """Raised when the configured Ethereum RPC endpoint rejects requests."""

    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class EthereumRPCClient:
    """Talosly blockchain data fetcher using JSON-RPC 2.0."""

    def __init__(self, rpc_url: str | None = None) -> None:
        self.rpc_url = rpc_url or settings.ethereum_rpc_url
        self._request_lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def _call(self, method: str, params: list[Any]) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        # Production deployments should use HTTPS RPC endpoints.
        async with httpx.AsyncClient(timeout=20) as client:
            for attempt in range(settings.ethereum_rpc_max_retries + 1):
                await self._throttle()
                response = await client.post(self.rpc_url, json=payload)
                if response.status_code != 429:
                    response.raise_for_status()
                    data = response.json()
                    break
                if attempt >= settings.ethereum_rpc_max_retries:
                    retry_after_seconds = self._retry_delay(response, attempt)
                    raise EthereumRPCRateLimitError(
                        f"Ethereum RPC rate limited method '{method}' after {attempt + 1} attempts",
                        retry_after_seconds=retry_after_seconds,
                    )
                await asyncio.sleep(self._retry_delay(response, attempt))
        if "error" in data:
            message = data["error"].get("message", "unknown error")
            raise RuntimeError(f"Talosly RPC error on {method}: {message}")
        return data["result"]

    async def _throttle(self) -> None:
        min_interval = max(settings.ethereum_rpc_min_interval_seconds, 0)
        if min_interval == 0:
            return
        async with self._request_lock:
            now = asyncio.get_running_loop().time()
            wait_seconds = self._last_request_at + min_interval - now
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
                now = asyncio.get_running_loop().time()
            self._last_request_at = now

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("retry-after")
        if retry_after:
            with contextlib.suppress(ValueError):
                return min(float(retry_after), 120)
        return min(2**attempt, 30)

    async def get_latest_block_number(self) -> int:
        return int(await self._call("eth_blockNumber", []), 16)

    async def get_block_transactions(self, block_number: int) -> list[dict[str, Any]]:
        block = await self._call("eth_getBlockByNumber", [hex(block_number), True])
        return block.get("transactions", []) if block else []

    async def get_transactions_for_address(
        self,
        address: str,
        from_block: int,
        to_block: int,
        block_transactions_cache: dict[int, list[dict[str, Any]]] | None = None,
    ) -> list[dict[str, Any]]:
        address_lower = address.lower()
        transactions: list[dict[str, Any]] = []
        for block_number in itertools.islice(range(from_block, to_block + 1), 5):
            if block_transactions_cache is not None and block_number in block_transactions_cache:
                block_transactions = block_transactions_cache[block_number]
            else:
                block_transactions = await self.get_block_transactions(block_number)
                if block_transactions_cache is not None:
                    block_transactions_cache[block_number] = block_transactions
            for tx in block_transactions:
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
            "status": receipt.get("status"),
            "logs": receipt.get("logs") or [],
        }
