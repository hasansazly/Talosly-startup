from datetime import datetime, timezone
import json

import pytest

from kya.baselines import get_baseline, update_baseline
from kya.ingest import AgentEvent
from scoring.layer3 import FEATURE_NAMES


class FakeProfilePool:
    def __init__(self) -> None:
        self.rows = {}

    async def fetchrow(self, _query, agent_id):
        baseline = self.rows.get(agent_id)
        return None if baseline is None else {"baseline": baseline}

    async def execute(self, _query, agent_id, baseline_json):
        self.rows[agent_id] = json.loads(baseline_json)
        return "INSERT 0 1"


def make_event(tx_hash: str) -> AgentEvent:
    return AgentEvent(
        tx_hash=tx_hash,
        agent_id=1,
        wallet="0xagent",
        counterparty="0xknown",
        value=1.0,
        selector="abcdef12",
        timestamp=datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
        raw={"hash": tx_hash},
    )


def feature_vector(first_value: float) -> dict[str, float]:
    return {
        name: first_value if index == 0 else float(index)
        for index, name in enumerate(FEATURE_NAMES)
    }


@pytest.fixture
def profile_pool(monkeypatch):
    pool = FakeProfilePool()

    async def fake_get_pool():
        return pool

    monkeypatch.setattr("kya.baselines.db.get_pool", fake_get_pool)
    return pool


@pytest.mark.asyncio
async def test_robust_stats_cold_start_is_low_confidence(profile_pool, monkeypatch):
    monkeypatch.setattr("kya.baselines.build_feature_vector", lambda _event, _baseline: feature_vector(5.0))

    baseline = await update_baseline(1, make_event("0x1"))
    robust_stats = baseline["robust_stats"]

    assert robust_stats["sample_count"] == 1
    assert robust_stats["low_confidence"] is True
    assert robust_stats["median"][0] == 5.0
    assert robust_stats["mad"][0] == 0.0
    assert robust_stats["covariance_method"] == "diagonal"
    assert await get_baseline(1) == baseline


@pytest.mark.asyncio
async def test_robust_stats_mad_matches_known_sample(profile_pool, monkeypatch):
    values = iter([1.0, 2.0, 100.0])
    monkeypatch.setattr(
        "kya.baselines.build_feature_vector",
        lambda _event, _baseline: feature_vector(next(values)),
    )

    for index in range(3):
        baseline = await update_baseline(1, make_event(f"0x{index}"))

    robust_stats = baseline["robust_stats"]
    assert robust_stats["median"][0] == 2.0
    assert robust_stats["mad"][0] == 1.0


@pytest.mark.asyncio
async def test_robust_stats_singular_covariance_falls_back_to_diagonal(profile_pool, monkeypatch):
    monkeypatch.setattr("kya.baselines.ROBUST_STATS_MIN_SAMPLES", 3)
    monkeypatch.setattr("kya.baselines.build_feature_vector", lambda _event, _baseline: feature_vector(5.0))

    for index in range(3):
        baseline = await update_baseline(1, make_event(f"0x{index}"))

    robust_stats = baseline["robust_stats"]
    covariance = robust_stats["covariance"]
    assert robust_stats["low_confidence"] is False
    assert robust_stats["covariance_method"] == "diagonal"
    assert all(
        covariance[row][column] == 0.0
        for row in range(len(FEATURE_NAMES))
        for column in range(len(FEATURE_NAMES))
        if row != column
    )
    assert all(covariance[index][index] > 0.0 for index in range(len(FEATURE_NAMES)))
