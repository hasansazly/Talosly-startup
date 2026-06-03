from datetime import datetime, timedelta, timezone
import json

import pytest

from kya.baselines import get_baseline, update_baseline
from kya.ingest import AgentEvent


class FakeProfilePool:
    def __init__(self) -> None:
        self.rows = {}

    async def fetchrow(self, _query, agent_id):
        baseline = self.rows.get(agent_id)
        if baseline is None:
            return None
        return {"baseline": baseline}

    async def execute(self, _query, agent_id, baseline_json):
        self.rows[agent_id] = json.loads(baseline_json)
        return "INSERT 0 1"


def make_event(
    *,
    agent_id: int = 1,
    tx_hash: str = "0x1",
    counterparty: str = "0xknown",
    value: float = 1.0,
    selector: str = "abcdef12",
    timestamp: datetime | None = None,
) -> AgentEvent:
    return AgentEvent(
        tx_hash=tx_hash,
        agent_id=agent_id,
        wallet="0xagent",
        counterparty=counterparty,
        value=value,
        selector=selector,
        timestamp=timestamp or datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
        raw={"hash": tx_hash},
    )


@pytest.fixture
def profile_pool(monkeypatch):
    pool = FakeProfilePool()

    async def fake_get_pool():
        return pool

    monkeypatch.setattr("kya.baselines.db.get_pool", fake_get_pool)
    return pool


@pytest.mark.asyncio
async def test_update_baseline_handles_first_ever_event(profile_pool):
    event = make_event()

    baseline = await update_baseline(1, event)
    persisted = await get_baseline(1)

    assert baseline == persisted
    assert baseline["event_count"] == 1
    assert baseline["confidence"] == 0.05
    assert baseline["known_counterparties"] == ["0xknown"]
    assert baseline["selectors_seen"] == ["abcdef12"]
    assert baseline["active_hours"] == {"12": 1}
    assert baseline["value_stats"]["mean"] == 1.0
    assert baseline["last_deviation"] == {
        "is_deviating": False,
        "score": 0.0,
        "reasons": ["cold_start"],
    }


@pytest.mark.asyncio
async def test_baseline_grows_incrementally_over_several_events(profile_pool):
    start = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    events = [
        make_event(tx_hash="0x1", counterparty="0xa", value=1.0, selector="11111111", timestamp=start),
        make_event(tx_hash="0x2", counterparty="0xb", value=2.0, selector="22222222", timestamp=start + timedelta(minutes=10)),
        make_event(tx_hash="0x3", counterparty="0xa", value=3.0, selector="11111111", timestamp=start + timedelta(minutes=20)),
        make_event(tx_hash="0x4", counterparty="0xc", value=4.0, selector="33333333", timestamp=start + timedelta(minutes=30)),
    ]

    baseline = None
    for event in events:
        baseline = await update_baseline(1, event)

    assert baseline is not None
    assert baseline["event_count"] == 4
    assert baseline["confidence"] == 0.2
    assert baseline["known_counterparties"] == ["0xa", "0xb", "0xc"]
    assert baseline["selectors_seen"] == ["11111111", "22222222", "33333333"]
    assert baseline["active_hours"] == {"12": 4}
    assert baseline["value_stats"]["count"] == 4
    assert baseline["value_stats"]["mean"] == 2.5
    assert baseline["value_stats"]["std"] > 1.0
    assert baseline["cadence_stats"]["count"] == 3
    assert baseline["cadence_stats"]["mean_seconds"] == 600.0


@pytest.mark.asyncio
async def test_deviating_event_is_flagged_against_existing_profile(profile_pool):
    start = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    for index, value in enumerate([1.0, 1.1, 0.9, 1.0, 1.05]):
        await update_baseline(
            1,
            make_event(
                tx_hash=f"0x{index}",
                counterparty="0xknown",
                value=value,
                selector="abcdef12",
                timestamp=start + timedelta(minutes=10 * index),
            ),
        )

    baseline = await update_baseline(
        1,
        make_event(
            tx_hash="0xdeviates",
            counterparty="0xnew",
            value=50.0,
            selector="deadbeef",
            timestamp=start + timedelta(hours=9),
        ),
    )

    assert baseline["last_deviation"]["is_deviating"] is True
    assert baseline["last_deviation"]["score"] >= 0.5
    assert set(baseline["last_deviation"]["reasons"]) >= {
        "new_counterparty",
        "new_selector",
        "value_outlier",
        "new_active_hour",
    }
    assert "0xnew" in baseline["known_counterparties"]
    assert "deadbeef" in baseline["selectors_seen"]
