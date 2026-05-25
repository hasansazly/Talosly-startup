from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

from scoring.layer5 import (
    AlertOrchestrator,
    EnrichedScoreResult,
    enrich_risk_factors,
    enrich_risk_summary,
    routing_decision,
)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def score_result(score: int = 82, summary: str = "Suspicious transaction"):
    result = MagicMock()
    result.tx_hash = "0xdeadbeef"
    result.risk_score = score
    result.risk_summary = summary
    result.risk_factors = ["FLASH_LOAN", "POOL_DRAIN"]
    return result


def layer3(score: float = 0.87):
    return {"ensemble_score": score, "mode": "heuristic"}


def layer4(
    verdict: str = "exploit",
    probability: float = 0.96,
    confidence: str = "high",
    action: str = "alert",
    fallback: bool = False,
):
    result = MagicMock()
    result.verdict = verdict
    result.exploit_probability = probability
    result.confidence = confidence
    result.recommended_action = action
    result.attack_type = "flash_loan"
    result.fallback_used = fallback
    result.reasoning = "Flash loan behavior with material pool drain."
    result.sub_signals = [
        {"signal": "flash_loan_fingerprint", "risk_contribution": "high"},
        {"signal": "pool_drain_ratio", "risk_contribution": "high"},
    ]
    return result


def protocol():
    return {"name": "Aave", "address": "0xprotocol"}


def transaction(tx_hash: str = "0xdeadbeef"):
    return {"tx_hash": tx_hash, "from_address": "0xattacker", "to_address": "0xprotocol"}


def orchestrator(telegram_sent: bool = True):
    database = MagicMock()
    telegram = MagicMock()
    database.update_transaction_score = AsyncMock()
    database.insert_alert = AsyncMock(return_value=42)
    database.mark_telegram_sent = AsyncMock()
    telegram.send_alert = AsyncMock(return_value=telegram_sent)
    return AlertOrchestrator(database, telegram), database, telegram


def test_routing_alert_action_boosts_to_threshold():
    decision = routing_decision(
        score_result=score_result(35),
        layer3=layer3(),
        layer4=layer4(verdict="suspicious", probability=0.42, action="alert"),
        threshold=70,
        recently_alerted=False,
    )

    assert decision.should_alert is True
    assert decision.enriched_score == 70


def test_routing_benign_caps_score_and_suppresses():
    decision = routing_decision(
        score_result=score_result(95),
        layer3=layer3(),
        layer4=layer4(verdict="benign", probability=0.03, confidence="high", action="skip"),
        threshold=70,
        recently_alerted=False,
    )

    assert decision.should_alert is False
    assert decision.enriched_score == 40


def test_routing_layer4_fallback_fails_open():
    decision = routing_decision(
        score_result=score_result(15),
        layer3=layer3(),
        layer4=layer4(verdict="suspicious", probability=0.60, action="alert", fallback=True),
        threshold=70,
        recently_alerted=False,
    )

    assert decision.should_alert is True
    assert decision.enriched_score == 70


def test_routing_monitor_action_suppresses():
    decision = routing_decision(
        score_result=score_result(82),
        layer3=layer3(),
        layer4=layer4(verdict="suspicious", probability=0.55, action="monitor"),
        threshold=70,
        recently_alerted=False,
    )

    assert decision.should_alert is False
    assert decision.reason == "layer4_action_monitor"


def test_process_saves_score_and_sends_telegram():
    layer5, database, telegram = orchestrator()

    result = run(
        layer5.process(
            tx_id=12,
            protocol=protocol(),
            transaction=transaction(),
            score_result=score_result(82),
            layer3=layer3(),
            layer4=layer4(),
            threshold=70,
        )
    )

    assert result.score_saved is True
    assert result.alert_created is True
    assert result.telegram_sent is True
    database.update_transaction_score.assert_called_once()
    database.insert_alert.assert_called_once()
    database.mark_telegram_sent.assert_called_once_with(42)
    telegram.send_alert.assert_called_once()


def test_process_low_score_saves_but_does_not_alert():
    layer5, database, telegram = orchestrator()

    result = run(
        layer5.process(
            tx_id=12,
            protocol=protocol(),
            transaction=transaction(),
            score_result=score_result(20),
            layer3=layer3(0.2),
            layer4=None,
            threshold=70,
        )
    )

    assert result.score_saved is True
    assert result.alert_created is False
    database.update_transaction_score.assert_called_once()
    database.insert_alert.assert_not_called()
    telegram.send_alert.assert_not_called()


def test_process_dedupes_second_alert_for_same_hash():
    layer5, _database, telegram = orchestrator()
    kwargs = {
        "tx_id": 12,
        "protocol": protocol(),
        "transaction": transaction(),
        "score_result": score_result(82),
        "layer3": layer3(),
        "layer4": layer4(),
        "threshold": 70,
    }

    first = run(layer5.process(**kwargs))
    second = run(layer5.process(**kwargs))

    assert first.alert_created is True
    assert second.alert_created is False
    assert telegram.send_alert.call_count == 1


def test_process_allows_same_hash_after_dedupe_window():
    layer5, _database, telegram = orchestrator()
    kwargs = {
        "tx_id": 12,
        "protocol": protocol(),
        "transaction": transaction(),
        "score_result": score_result(82),
        "layer3": layer3(),
        "layer4": layer4(),
        "threshold": 70,
    }

    run(layer5.process(**kwargs))
    layer5._recent_alerts["0xdeadbeef"] = time.time() - 9999
    result = run(layer5.process(**kwargs))

    assert result.alert_created is True
    assert telegram.send_alert.call_count == 2


def test_process_handles_telegram_failure_without_raising():
    layer5, database, telegram = orchestrator(telegram_sent=False)

    result = run(
        layer5.process(
            tx_id=12,
            protocol=protocol(),
            transaction=transaction(),
            score_result=score_result(82),
            layer3=layer3(),
            layer4=layer4(),
            threshold=70,
        )
    )

    assert result.alert_created is True
    assert result.telegram_sent is False
    database.mark_telegram_sent.assert_not_called()
    telegram.send_alert.assert_called_once()


def test_process_handles_insert_alert_failure_without_raising():
    layer5, database, telegram = orchestrator()
    database.insert_alert = AsyncMock(side_effect=Exception("db down"))

    result = run(
        layer5.process(
            tx_id=12,
            protocol=protocol(),
            transaction=transaction(),
            score_result=score_result(82),
            layer3=layer3(),
            layer4=layer4(),
            threshold=70,
        )
    )

    assert result.alert_created is False
    telegram.send_alert.assert_not_called()


def test_enriched_summary_includes_layer3_and_layer4_context():
    summary = enrich_risk_summary(score_result(), layer3(), layer4())

    assert "Layer 3 ML score 0.87" in summary
    assert "Layer 4: exploit" in summary
    assert "Flash loan behavior" in summary


def test_enriched_factors_include_layer4_signals_without_breaking_limit():
    factors = enrich_risk_factors(score_result(), layer4())

    assert len(factors) <= 3
    assert any("L4_HIGH" in factor for factor in factors)


def test_enriched_score_result_forwards_unknown_fields():
    original = score_result()
    original.custom_field = "kept"
    enriched = EnrichedScoreResult(original, 99, "new summary", ["NEW_FACTOR"])

    assert enriched.risk_score == 99
    assert enriched.risk_summary == "new summary"
    assert enriched.custom_field == "kept"
