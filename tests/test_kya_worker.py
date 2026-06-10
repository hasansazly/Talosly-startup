from unittest.mock import AsyncMock

import pytest

from backend import worker as worker_module
from backend.worker import TaloslyWorker


@pytest.mark.asyncio
async def test_kya_worker_loop_is_skipped_when_flag_off(monkeypatch):
    worker = TaloslyWorker.__new__(TaloslyWorker)
    worker.rpc = type("RPC", (), {"sanitized_rpc_url": lambda _self: "https://example.test"})()

    poll_loop = AsyncMock()
    kya_loop = AsyncMock()
    shutdown = AsyncMock()
    init_db = AsyncMock()

    monkeypatch.delenv("ENABLE_KYA", raising=False)
    monkeypatch.setattr(worker_module.kya_settings, "enable_kya", False)
    monkeypatch.setattr(worker_module.settings, "protocol_flow_enabled", True)
    monkeypatch.setattr(worker_module.settings, "enable_mempool_subscriber", False)
    monkeypatch.setattr(worker_module.settings, "enable_rpc_polling", False)
    monkeypatch.setattr(worker_module.db, "init_db", init_db)
    monkeypatch.setattr(worker, "_risk_threshold", AsyncMock(return_value=70))
    monkeypatch.setattr(worker, "_poll_loop", poll_loop)
    monkeypatch.setattr(worker, "_run_kya_loop", kya_loop)
    monkeypatch.setattr(worker, "shutdown", shutdown)

    await worker.run()

    init_db.assert_awaited_once()
    poll_loop.assert_awaited_once()
    kya_loop.assert_not_awaited()
    shutdown.assert_awaited_once_with("stop requested")
