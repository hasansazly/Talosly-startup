"""Integration smoke tests — require a live Postgres instance.

Run with:
    docker compose -f docker-compose.test.yml up -d
    pytest --integration tests/integration/
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import asyncpg
import pytest

from kya.baselines import update_baseline
from kya.bocpd import bocpd_update, empty_bocpd_state
from kya.ingest import AgentEvent

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_api_key(pool: asyncpg.Pool, suffix: str = "1") -> int:
    return await pool.fetchval(
        "INSERT INTO api_keys (key_hash, key_prefix) VALUES ($1, 'tls_') RETURNING id",
        f"test_hash_{suffix}",
    )


async def _insert_agent(pool: asyncpg.Pool, api_key_id: int, suffix: str = "1") -> int:
    return await pool.fetchval(
        """INSERT INTO agents (name, principal_ref, owner_api_key_id)
           VALUES ($1, $2, $3) RETURNING id""",
        f"test-agent-{suffix}",
        f"agent://test-{suffix}",
        api_key_id,
    )


def _make_event(agent_id: int, tx_hash: str = "0xabc") -> AgentEvent:
    return AgentEvent(
        tx_hash=tx_hash,
        agent_id=agent_id,
        wallet="0xwallet",
        counterparty="0xcounterparty",
        value=1.0,
        selector="abcdef12",
        timestamp=datetime.now(timezone.utc),
        raw={},
    )


# ---------------------------------------------------------------------------
# Test 1 — schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migrations_apply_cleanly(real_db: asyncpg.Pool):
    """All expected tables must exist after _create_tables() runs."""
    rows = await real_db.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    )
    names = {r["tablename"] for r in rows}
    expected = {
        "protocols",
        "transactions",
        "alerts",
        "api_keys",
        "waitlist",
        "request_log",
        "scoring_metrics",
        "settings",
        "agents",
        "agent_wallets",
        "agent_profiles",
        "agent_scores",
        "action_receipts",
    }
    assert expected <= names, f"missing tables: {expected - names}"


# ---------------------------------------------------------------------------
# Test 2 — append-only trigger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_receipt_trigger_blocks_update_and_delete(real_db: asyncpg.Pool):
    """The append-only trigger must reject both UPDATE and DELETE on action_receipts.

    This is the legal backbone of the evidence layer — FakePool never executed
    this trigger SQL so it was untested until now.
    """
    key_id = await _insert_api_key(real_db, "trigger")
    agent_id = await _insert_agent(real_db, key_id, "trigger")

    await real_db.execute(
        """INSERT INTO action_receipts (agent_id, content_hash, prev_hash, signature, payload)
           VALUES ($1, 'hash_trigger', NULL, 'sig_trigger', '{"v": 1}'::jsonb)""",
        agent_id,
    )

    with pytest.raises(asyncpg.PostgresError, match="append-only"):
        await real_db.execute(
            "UPDATE action_receipts SET payload = '{\"v\": 2}'::jsonb WHERE agent_id = $1",
            agent_id,
        )

    with pytest.raises(asyncpg.PostgresError, match="append-only"):
        await real_db.execute(
            "DELETE FROM action_receipts WHERE agent_id = $1",
            agent_id,
        )

    count = await real_db.fetchval(
        "SELECT COUNT(*) FROM action_receipts WHERE agent_id = $1", agent_id
    )
    assert count == 1


# ---------------------------------------------------------------------------
# Test 3 — BOCPD JSONB round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bocpd_state_roundtrip(real_db: asyncpg.Pool):
    """BOCPD state must survive a JSONB write → read cycle without loss."""
    key_id = await _insert_api_key(real_db, "bocpd")
    agent_id = await _insert_agent(real_db, key_id, "bocpd")

    state = empty_bocpd_state()
    # Feed a mix of normal values and one outlier to build non-trivial state.
    for x in [0.1, 0.2, 0.15, 5.0, 0.12]:
        state = bocpd_update(state, x)

    await real_db.execute(
        "INSERT INTO agent_profiles (agent_id, baseline) VALUES ($1, $2::jsonb)",
        agent_id,
        json.dumps({"bocpd": state}),
    )

    row = await real_db.fetchrow(
        "SELECT baseline FROM agent_profiles WHERE agent_id = $1", agent_id
    )
    raw = row["baseline"]
    loaded = json.loads(raw) if isinstance(raw, str) else dict(raw)
    stored = loaded["bocpd"]

    assert stored["event_count"] == state["event_count"] == 5
    assert stored["cp_prob"] == state["cp_prob"]
    assert len(stored["run_probs"]) == len(state["run_probs"])
    assert len(stored["nig_runs"]) == len(state["nig_runs"])


# ---------------------------------------------------------------------------
# Test 4 — concurrent update_baseline (regression for BOCPD race condition)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_score_same_agent_incorporates_both_events(real_db: asyncpg.Pool):
    """Two concurrent update_baseline calls for the same agent must both commit.

    Without the SELECT FOR UPDATE row lock, one call reads stale state and its
    write clobbers the other — the final event_count would be 1, not 2.
    """
    key_id = await _insert_api_key(real_db, "concurrent")
    agent_id = await _insert_agent(real_db, key_id, "concurrent")

    await asyncio.gather(
        update_baseline(agent_id, _make_event(agent_id, "0xaaa")),
        update_baseline(agent_id, _make_event(agent_id, "0xbbb")),
    )

    row = await real_db.fetchrow(
        "SELECT baseline FROM agent_profiles WHERE agent_id = $1", agent_id
    )
    raw = row["baseline"]
    baseline = json.loads(raw) if isinstance(raw, str) else dict(raw)
    assert baseline["event_count"] == 2, (
        f"expected 2 but got {baseline['event_count']} — "
        "the row lock is not protecting against concurrent writes"
    )
