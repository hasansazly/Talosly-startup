from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend import worker as worker_module
from backend.worker import TaloslyWorker


def test_parse_mempool_transaction_normalizes_pending_fields():
    worker = TaloslyWorker.__new__(TaloslyWorker)

    parsed = worker._parse_mempool_transaction(
        {
            "hash": "0xabc",
            "from": "0xsender",
            "to": "0xprotocol",
            "value": hex(2 * 10**18),
            "gas": hex(500_000),
            "gasPrice": hex(30 * 10**9),
            "input": "0x12345678",
        }
    )

    assert parsed["tx_hash"] == "0xabc"
    assert parsed["from_address"] == "0xsender"
    assert parsed["to_address"] == "0xprotocol"
    assert parsed["value_eth"] == 2
    assert parsed["gas_used"] == 500_000
    assert parsed["gas_price_gwei"] == 30
    assert parsed["block_number"] is None


@pytest.mark.asyncio
async def test_mempool_alert_flows_through_layer5(monkeypatch):
    worker = TaloslyWorker.__new__(TaloslyWorker)
    protocol = {"id": 7, "name": "Aave", "address": "0xprotocol"}
    worker.mempool_protocols = {"0xprotocol": protocol}
    worker.telegram = MagicMock()

    worker.pre_filter = MagicMock()
    worker.pre_filter.should_evaluate.return_value = (True, "escalate")

    worker.layer2 = MagicMock()
    worker.layer2.process.return_value.to_dict.return_value = {"flash_loan_fingerprint": 1.0}

    worker.layer3 = MagicMock()
    worker.layer3.score.return_value.to_dict.return_value = {
        "ensemble_score": 0.91,
        "escalate_to_llm": True,
    }

    layer4_result = SimpleNamespace(
        should_alert=True,
        verdict="exploit",
        exploit_probability=0.95,
        confidence="high",
        recommended_action="alert",
        attack_type="flash_loan",
        fallback_used=False,
        layer3_score=0.91,
        to_dict=lambda: {"recommended_action": "alert"},
    )
    worker.layer4 = MagicMock()
    worker.layer4.analyze = AsyncMock(return_value=layer4_result)

    score_result = SimpleNamespace(
        tx_hash="0xabc",
        risk_score=90,
        risk_summary="Suspicious pending tx",
        risk_factors=["FLASH_LOAN"],
    )
    worker.scorer = MagicMock()
    worker.scorer.score_transaction = AsyncMock(return_value=score_result)

    layer5_result = SimpleNamespace(
        alert_created=True,
        alert_id=42,
        telegram_sent=True,
        decision=SimpleNamespace(enriched_score=95, reason="all_gates_passed"),
    )
    worker.layer5 = MagicMock()
    worker.layer5.process = AsyncMock(return_value=layer5_result)

    upsert_transaction = AsyncMock(return_value=(123, True))
    get_app_setting = AsyncMock(return_value=70)
    monkeypatch.setattr(worker_module.db, "upsert_transaction", upsert_transaction)
    monkeypatch.setattr(worker_module.db, "get_app_setting", get_app_setting)

    await worker._process_mempool_transaction(
        {
            "hash": "0xabc",
            "from": "0xsender",
            "to": "0xprotocol",
            "value": "0x0",
            "gas": hex(750_000),
            "input": "0xd9d98ce4" + "00" * 100,
        }
    )

    upsert_transaction.assert_awaited_once()
    worker.scorer.score_transaction.assert_awaited_once()
    worker.layer5.process.assert_awaited_once()
    call_kwargs = worker.layer5.process.await_args.kwargs
    assert call_kwargs["tx_id"] == 123
    assert call_kwargs["protocol"] == protocol
    assert call_kwargs["transaction"]["tx_hash"] == "0xabc"
    assert call_kwargs["threshold"] == 70
