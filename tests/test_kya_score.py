from datetime import datetime, timezone
import json

import pytest

from kya.ingest import AgentEvent
from kya.score import score_agent_event


class FakeScorePool:
    def __init__(self) -> None:
        self.rows = []

    async def fetchrow(self, _query, *_args):
        return None  # no prior receipts

    async def execute(self, query, *args):
        if "agent_scores" in query:
            agent_id, trust_score, risk_factors_json, shap_top_json, confidence = args
            self.rows.append(
                {
                    "agent_id": agent_id,
                    "trust_score": trust_score,
                    "risk_factors": json.loads(risk_factors_json),
                    "shap_top": json.loads(shap_top_json),
                    "confidence": confidence,
                }
            )
        return "INSERT 0 1"


@pytest.fixture
def score_pool(monkeypatch):
    pool = FakeScorePool()

    async def fake_get_pool():
        return pool

    monkeypatch.setattr("kya.score.db.get_pool", fake_get_pool)
    return pool


def mature_baseline() -> dict:
    return {
        "event_count": 25,
        "confidence": 1.0,
        "known_counterparties": ["0xknown"],
        "selectors_seen": ["abcdef12"],
        "active_hours": {"12": 25},
        "value_stats": {"count": 25, "mean": 1.0, "std": 0.1},
        "cadence_stats": {
            "count": 12,
            "mean_seconds": 600.0,
            "std_seconds": 30.0,
            "last_timestamp": datetime(2026, 1, 1, 12, tzinfo=timezone.utc).isoformat(),
        },
    }


def make_event(
    *,
    tx_hash: str,
    counterparty: str,
    value: float,
    selector: str,
    timestamp: datetime,
    raw: dict | None = None,
) -> AgentEvent:
    return AgentEvent(
        tx_hash=tx_hash,
        agent_id=1,
        wallet="0xagent",
        counterparty=counterparty,
        value=value,
        selector=selector,
        timestamp=timestamp,
        raw=raw or {"input": f"0x{selector}", "sender_first_seen_ts": datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()},
    )


@pytest.mark.asyncio
async def test_baseline_consistent_event_scores_low_risk(score_pool):
    event = make_event(
        tx_hash="0xnormal",
        counterparty="0xknown",
        value=1.02,
        selector="abcdef12",
        timestamp=datetime(2026, 1, 1, 12, 10, tzinfo=timezone.utc),
    )

    score = await score_agent_event(1, event, mature_baseline())

    assert score.trust_score >= 70
    assert "new_counterparty" not in score.risk_factors
    assert "value_outlier" not in score.risk_factors
    assert len(score.shap_top) == 3
    assert score.confidence > 0
    assert score_pool.rows[-1]["trust_score"] == score.trust_score
    assert score_pool.rows[-1]["shap_top"] == score.shap_top


@pytest.mark.asyncio
async def test_strongly_deviating_event_scores_high_risk_with_shap(score_pool):
    event = make_event(
        tx_hash="0xdeviates",
        counterparty="0xnew",
        value=50.0,
        selector="deadbeef",
        timestamp=datetime(2026, 1, 1, 14, tzinfo=timezone.utc),
        raw={
            "input": "0xdeadbeef" + "00" * 16,
            "sender_first_seen_ts": datetime(2026, 1, 1, 13, tzinfo=timezone.utc).timestamp(),
            "tornado_tagged": True,
        },
    )

    score = await score_agent_event(1, event, mature_baseline())

    assert score.trust_score <= 40
    assert {"new_counterparty", "unseen_selector", "off_hours", "cadence_break", "value_outlier"} <= set(score.risk_factors)
    assert len(score.shap_top) == 3
    assert any(item["shap"] > 0 for item in score.shap_top)
    assert score.layer3["mode"] == "heuristic"
    assert score_pool.rows[-1]["risk_factors"] == score.risk_factors
