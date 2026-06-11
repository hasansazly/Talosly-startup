"""Rolling KYA behavioral baselines persisted in ``agent_profiles``."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from backend import database as db
from kya.ingest import AgentEvent
from kya.bocpd import bocpd_score, bocpd_update, empty_bocpd_state
from kya.sequence import compute_neg_log_prob, score_transition, state_from_event, update_sequence

MAX_SET_ITEMS = 200
MIN_EVENTS_FOR_DEVIATION = 3


def _empty_baseline() -> dict[str, Any]:
    return {
        "version": 1,
        "event_count": 0,
        "confidence": 0.0,
        "known_counterparties": [],
        "selectors_seen": [],
        "active_hours": {},
        "value_stats": {
            "count": 0,
            "mean": 0.0,
            "m2": 0.0,
            "std": 0.0,
            "min": None,
            "max": None,
        },
        "cadence_stats": {
            "count": 0,
            "mean_seconds": 0.0,
            "m2": 0.0,
            "std_seconds": 0.0,
            "min_seconds": None,
            "max_seconds": None,
            "last_timestamp": None,
        },
        "last_deviation": {
            "is_deviating": False,
            "score": 0.0,
            "reasons": [],
            "sequence_anomaly": 0.0,
            "bocpd_cp_prob": 0.0,
        },
        "sequence": {
            "prev_state": None,
            "transitions": {},
            "transition_count": 0,
            "log_prob_stats": {"count": 0, "mean": 0.0, "m2": 0.0, "std": 0.0},
        },
        "bocpd": empty_bocpd_state(),
    }


async def get_baseline(agent_id: int) -> dict[str, Any]:
    """Return the persisted baseline for an agent, or a safe cold-start profile."""
    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT baseline FROM agent_profiles WHERE agent_id = $1", agent_id)
    if not row:
        return _empty_baseline()
    return _normalize_baseline(row["baseline"])


async def update_baseline(agent_id: int, event: AgentEvent) -> dict[str, Any]:
    """Incrementally update one agent baseline and persist it to ``agent_profiles``.

    Uses SELECT FOR UPDATE inside a transaction so concurrent events for the same
    agent cannot race and silently drop BOCPD observations.
    """
    pool = await db.get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT baseline FROM agent_profiles WHERE agent_id = $1 FOR UPDATE",
                agent_id,
            )
            baseline = _normalize_baseline(row["baseline"]) if row else _empty_baseline()
            deviation = _detect_deviation(baseline, event)
            updated = _apply_event(baseline, event)
            updated["last_deviation"] = deviation
            await conn.execute(
                """
                INSERT INTO agent_profiles (agent_id, baseline, updated_at)
                VALUES ($1, $2::jsonb, NOW())
                ON CONFLICT (agent_id) DO UPDATE SET
                    baseline = EXCLUDED.baseline,
                    updated_at = NOW()
                """,
                agent_id,
                json.dumps(updated, sort_keys=True),
            )
    return updated


def _normalize_baseline(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = {}
    baseline = _empty_baseline()
    if isinstance(value, dict):
        baseline.update(value)
        baseline["value_stats"] = {**_empty_baseline()["value_stats"], **value.get("value_stats", {})}
        baseline["cadence_stats"] = {**_empty_baseline()["cadence_stats"], **value.get("cadence_stats", {})}
        baseline["last_deviation"] = {**_empty_baseline()["last_deviation"], **value.get("last_deviation", {})}
        baseline["sequence"] = {**_empty_baseline()["sequence"], **value.get("sequence", {})}
        baseline["bocpd"] = {**empty_bocpd_state(), **value.get("bocpd", {})}
    return baseline


def _apply_event(baseline: dict[str, Any], event: AgentEvent) -> dict[str, Any]:
    updated = deepcopy(baseline)
    # Capture pre-event known counterparties so the state label matches _detect_deviation.
    pre_known_cp = {str(c).lower() for c in updated.get("known_counterparties") or []}

    updated["event_count"] = int(updated.get("event_count") or 0) + 1
    updated["confidence"] = _confidence(updated["event_count"])

    if event.counterparty:
        updated["known_counterparties"] = _append_unique(updated.get("known_counterparties", []), event.counterparty.lower())
    if event.selector:
        updated["selectors_seen"] = _append_unique(updated.get("selectors_seen", []), event.selector.lower())

    active_hours = dict(updated.get("active_hours") or {})
    hour = str(_event_timestamp(event).hour)
    active_hours[hour] = int(active_hours.get(hour) or 0) + 1
    updated["active_hours"] = active_hours

    updated["value_stats"] = _update_running_stats(
        updated.get("value_stats") or {},
        float(event.value or 0.0),
        mean_key="mean",
        std_key="std",
    )
    updated["cadence_stats"] = _update_cadence(updated.get("cadence_stats") or {}, _event_timestamp(event))

    seq = dict(updated.get("sequence") or _empty_baseline()["sequence"])
    curr_state = state_from_event(event.selector, event.counterparty, float(event.value or 0.0), pre_known_cp)
    prev_state = seq.get("prev_state")
    nlp = compute_neg_log_prob(seq, prev_state or "", curr_state) if prev_state else None
    updated["sequence"] = update_sequence(seq, prev_state, curr_state, nlp)

    x_bocpd = math.log(float(event.value or 0) + 1e-9)
    updated["bocpd"] = bocpd_update(updated.get("bocpd"), x_bocpd)
    return updated


def _detect_deviation(baseline: dict[str, Any], event: AgentEvent) -> dict[str, Any]:
    event_count = int(baseline.get("event_count") or 0)
    if event_count < MIN_EVENTS_FOR_DEVIATION:
        return {"is_deviating": False, "score": 0.0, "reasons": ["cold_start"], "sequence_anomaly": 0.0, "bocpd_cp_prob": 0.0}

    score = 0.0
    reasons: list[str] = []
    counterparty = (event.counterparty or "").lower()
    if counterparty and counterparty not in set(baseline.get("known_counterparties") or []):
        score += 0.35
        reasons.append("new_counterparty")

    selector = (event.selector or "").lower()
    if selector and selector not in set(baseline.get("selectors_seen") or []):
        score += 0.25
        reasons.append("new_selector")

    value_z = _zscore(float(event.value or 0.0), baseline.get("value_stats") or {}, "mean", "std")
    if value_z >= 3.0:
        score += min(0.45, 0.15 + value_z / 20)
        reasons.append("value_outlier")

    cadence_z = _cadence_zscore(event, baseline.get("cadence_stats") or {})
    if cadence_z is not None and cadence_z >= 3.0:
        score += min(0.25, 0.10 + cadence_z / 25)
        reasons.append("cadence_outlier")

    hour = str(_event_timestamp(event).hour)
    if hour not in set((baseline.get("active_hours") or {}).keys()):
        score += 0.10
        reasons.append("new_active_hour")

    pre_known_cp = {str(c).lower() for c in baseline.get("known_counterparties") or []}
    seq = baseline.get("sequence") or {}
    curr_state = state_from_event(event.selector, event.counterparty, float(event.value or 0.0), pre_known_cp)
    seq_anomaly = score_transition(seq, seq.get("prev_state") or "", curr_state)
    if seq_anomaly >= 0.5:
        score += seq_anomaly * 0.40
        reasons.append("sequence_break")

    x_bocpd = math.log(float(event.value or 0) + 1e-9)
    cp_prob = bocpd_score(baseline.get("bocpd"), x_bocpd)
    if cp_prob >= 0.3:
        score += cp_prob * 0.45
    if cp_prob >= 0.5:
        reasons.append("regime_change")

    score = round(min(score, 1.0), 4)
    return {
        "is_deviating": score >= 0.5,
        "score": score,
        "reasons": reasons,
        "sequence_anomaly": round(seq_anomaly, 4),
        "bocpd_cp_prob": round(cp_prob, 4),
    }


def _update_running_stats(stats: dict[str, Any], value: float, *, mean_key: str, std_key: str) -> dict[str, Any]:
    count = int(stats.get("count") or 0) + 1
    previous_mean = float(stats.get(mean_key) or 0.0)
    previous_m2 = float(stats.get("m2") or 0.0)
    delta = value - previous_mean
    mean = previous_mean + delta / count
    delta2 = value - mean
    m2 = previous_m2 + delta * delta2
    variance = m2 / (count - 1) if count > 1 else 0.0
    return {
        "count": count,
        mean_key: round(mean, 8),
        "m2": round(m2, 8),
        std_key: round(math.sqrt(max(variance, 0.0)), 8),
        "min": value if stats.get("min") is None else min(float(stats["min"]), value),
        "max": value if stats.get("max") is None else max(float(stats["max"]), value),
    }


def _update_cadence(stats: dict[str, Any], timestamp: datetime) -> dict[str, Any]:
    updated = dict(stats)
    last_timestamp = _parse_timestamp(updated.get("last_timestamp"))
    if last_timestamp is not None:
        interval = max((timestamp - last_timestamp).total_seconds(), 0.0)
        updated = _update_running_stats(
            {
                "count": updated.get("count"),
                "mean_seconds": updated.get("mean_seconds"),
                "m2": updated.get("m2"),
                "std_seconds": updated.get("std_seconds"),
                "min": updated.get("min_seconds"),
                "max": updated.get("max_seconds"),
            },
            interval,
            mean_key="mean_seconds",
            std_key="std_seconds",
        )
        updated["min_seconds"] = updated.pop("min")
        updated["max_seconds"] = updated.pop("max")
    updated["last_timestamp"] = timestamp.astimezone(timezone.utc).isoformat()
    return updated


def _cadence_zscore(event: AgentEvent, stats: dict[str, Any]) -> float | None:
    last_timestamp = _parse_timestamp(stats.get("last_timestamp"))
    if last_timestamp is None or int(stats.get("count") or 0) < 2:
        return None
    interval = max((_event_timestamp(event) - last_timestamp).total_seconds(), 0.0)
    return _zscore(interval, stats, "mean_seconds", "std_seconds")


def _zscore(value: float, stats: dict[str, Any], mean_key: str, std_key: str) -> float:
    count = int(stats.get("count") or 0)
    std = float(stats.get(std_key) or 0.0)
    if count < 2 or std <= 0:
        return 0.0
    return abs(value - float(stats.get(mean_key) or 0.0)) / std


def _append_unique(items: list[Any], value: str) -> list[str]:
    normalized = [str(item).lower() for item in items if item]
    if value not in normalized:
        normalized.append(value)
    return normalized[-MAX_SET_ITEMS:]


def _confidence(event_count: int) -> float:
    return round(min(max(event_count, 0) / 20, 1.0), 4)


def _event_timestamp(event: AgentEvent) -> datetime:
    timestamp = event.timestamp
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _event_timestamp(AgentEvent("", 0, "", None, 0, "", value, {}))
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


__all__ = ["get_baseline", "update_baseline"]
