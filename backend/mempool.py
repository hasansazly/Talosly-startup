import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

import websockets

from backend.services.logger import logger

_BACKOFF_INITIAL_SECONDS = 5
_BACKOFF_MAX_SECONDS = 60

TransactionHandler = Callable[[dict[str, Any]], Awaitable[None]]


def _log_task_exception(task: asyncio.Task) -> None:
    """Log exceptions from fire-and-forget transaction handler tasks."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.error("mempool.handler.error", task_name=task.get_name(), error=str(exc))


class MempoolSubscriber:
    """Persistent Alchemy pending-transaction subscriber."""

    def __init__(self, wss_url: str, tx_handler_callback: TransactionHandler, to_addresses: list[str] | None = None) -> None:
        self.wss_url = wss_url
        self.tx_handler = tx_handler_callback
        self.to_addresses = sorted({address for address in (to_addresses or []) if address})
        self.is_running = False
        self.websocket: Any | None = None

    async def start(self) -> None:
        self.is_running = True
        retry_delay = _BACKOFF_INITIAL_SECONDS

        while self.is_running:
            try:
                logger.info("mempool.connecting")
                async with websockets.connect(
                    self.wss_url,
                    open_timeout=10,
                    ping_interval=20,
                    ping_timeout=10,
                ) as websocket:
                    self.websocket = websocket
                    await websocket.send(json.dumps(self._subscription_payload()))

                    ack = json.loads(await websocket.recv())
                    if "error" in ack:
                        raise RuntimeError(f"Alchemy pending transaction subscription failed: {ack['error']}")

                    logger.info("mempool.subscribed", subscription_id=ack.get("result"), to_address_count=len(self.to_addresses))
                    retry_delay = _BACKOFF_INITIAL_SECONDS

                    async for raw_message in websocket:
                        tx = self._extract_transaction(raw_message)
                        if not tx:
                            continue
                        task = asyncio.create_task(self.tx_handler(tx), name=f"mempool:{tx.get('hash', 'unknown')}")
                        task.add_done_callback(_log_task_exception)
            except websockets.exceptions.ConnectionClosed as exc:
                logger.warning("mempool.connection.closed", error=str(exc), retry_delay=retry_delay)
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, _BACKOFF_MAX_SECONDS)
            except Exception as exc:
                logger.error("mempool.loop.error", error=str(exc), retry_delay=retry_delay)
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, _BACKOFF_MAX_SECONDS)
            finally:
                self.websocket = None

    def stop(self) -> None:
        self.is_running = False
        if self.websocket:
            with contextlib.suppress(RuntimeError):
                asyncio.get_running_loop().create_task(self.websocket.close())
        logger.info("mempool.stopped")

    def _subscription_payload(self) -> dict[str, Any]:
        params: list[Any] = ["alchemy_pendingTransactions"]
        if self.to_addresses:
            params.append({"toAddress": self.to_addresses, "hashesOnly": False})
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_subscribe",
            "params": params,
        }

    @staticmethod
    def _extract_transaction(raw_message: str) -> dict[str, Any] | None:
        try:
            response = json.loads(raw_message)
        except json.JSONDecodeError as exc:
            logger.warning("mempool.message.invalid_json", error=str(exc))
            return None

        tx = response.get("params", {}).get("result")
        return tx if isinstance(tx, dict) else None
