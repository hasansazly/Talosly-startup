"""Rolling KYA behavioral baselines persisted in ``agent_profiles``."""

from __future__ import annotations

import json
import math
import os
import warnings
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

import numpy as np
from sklearn.covariance import LedoitWolf, MinCovDet

from backend import database as db
from kya.features import build_feature_vector
from kya.ingest import AgentEvent
from scoring.layer3 import FEATURE_NAMES

MAX_SET_ITEMS = 200
MIN_EVENTS_FOR_DEVIATION = 3
ROBUST_STATS_WINDOW_SIZE = max(int(os.getenv("KYA_ROBUST_STATS_WINDOW_SIZE", "200")), 1)
ROBUST_STATS_MIN_SAMPLES = max(int(os.getenv("KYA_ROBUST_STATS_MIN_SAMPLES", "20")), 1)
ROBUST_STATS_COVARIANCE_INTERVAL = max(int(os.getenv("KYA_ROBUST_STATS_COVARIANCE_INTERVAL", "5")), 1)
ROBUST_STATS_DIAGONAL_FLOOR = 1e-8


def _empty_cusum_state() -> dict[str, Any]:
    return {
        "s_high": 0.0,
        "s_low": 0.0,
        "reference_mean": None,
        "count": 0,
    }


def _empty_conformal_calib() -> dict[str, Any]:
    return {
        "scores": [],
        "sample_count": 0,
    }


def _empty_robust_stats() -> dict[str, Any]:
    feature_count = len(FEATURE_NAMES)
    return {
        "feature_names": list(FEATURE_NAMES),
        "sample_count": 0,
        "observation_count": 0,
        "window_size": ROBUST_STATS_WINDOW_SIZE,
        "min_samples": ROBUST_STATS_MIN_SAMPLES,
        "low_confidence": True,
        "median": [0.0] * feature_count,
        "mad": [0.0] * feature_count,
        "covariance": _diagonal_covariance(np.zeros((0, feature_count))).tolist(),
        "covariance_method": "diagonal",
        "covariance_sample_count": 0,
        "covariance_observation_count": 0,
        "samples": [],
    }


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
        },
        "robust_stats": _empty_robust_stats(),
        "cusum_state": _empty_cusum_state(),
        "conformal_calib": _empty_conformal_calib(),
    }


async def get_baseline(agent_id: int) -> dict[str, Any]:
    """Return the persisted baseline for an agent, or a safe cold-start profile."""
    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT baseline FROM agent_profiles WHERE agent_id = $1", agent_id)
    if not row:
        return _empty_baseline()
    return _normalize_baseline(row["baseline"])


async def update_baseline(
    agent_id: int,
    event: AgentEvent,
    feature_vector: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Incrementally update one agent baseline and persist it to ``agent_profiles``."""
    baseline = await get_baseline(agent_id)
    deviation = _detect_deviation(baseline, event)
    updated = _apply_event(baseline, event, feature_vector)
    updated["last_deviation"] = deviation

    pool = await db.get_pool()
    await pool.execute(
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
        baseline["robust_stats"] = {**_empty_robust_stats(), **value.get("robust_stats", {})}
        baseline["cusum_state"] = {**_empty_cusum_state(), **value.get("cusum_state", {})}
        baseline["conformal_calib"] = {**_empty_conformal_calib(), **value.get("conformal_calib", {})}
    return baseline


def _apply_event(
    baseline: dict[str, Any],
    event: AgentEvent,
    feature_vector: dict[str, Any] | None = None,
) -> dict[str, Any]:
    updated = deepcopy(baseline)
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
    updated["robust_stats"] = _update_robust_stats(
        updated.get("robust_stats") or {},
        feature_vector or build_feature_vector(event, baseline),
    )
    return updated


def _update_robust_stats(stats: dict[str, Any], features: dict[str, Any]) -> dict[str, Any]:
    normalized = {**_empty_robust_stats(), **stats}
    sample = [_numeric_feature(features.get(name, 0.0)) for name in FEATURE_NAMES]
    samples = [
        [_numeric_feature(value) for value in row]
        for row in normalized.get("samples") or []
        if isinstance(row, list) and len(row) == len(FEATURE_NAMES)
    ]
    samples.append(sample)
    samples = samples[-ROBUST_STATS_WINDOW_SIZE:]

    matrix = np.asarray(samples, dtype=float)
    median = np.median(matrix, axis=0)
    mad = np.median(np.abs(matrix - median), axis=0)
    sample_count = len(samples)
    observation_count = int(normalized.get("observation_count") or 0) + 1
    low_confidence = sample_count < ROBUST_STATS_MIN_SAMPLES
    covariance_sample_count = int(normalized.get("covariance_sample_count") or 0)
    covariance_observation_count = int(normalized.get("covariance_observation_count") or 0)
    should_recompute = (
        low_confidence
        or covariance_sample_count < ROBUST_STATS_MIN_SAMPLES
        or observation_count - covariance_observation_count >= ROBUST_STATS_COVARIANCE_INTERVAL
    )

    covariance = normalized.get("covariance")
    covariance_method = str(normalized.get("covariance_method") or "diagonal")
    if should_recompute:
        covariance, covariance_method = _robust_covariance(matrix, low_confidence=low_confidence)
        covariance_sample_count = sample_count
        covariance_observation_count = observation_count

    return {
        "feature_names": list(FEATURE_NAMES),
        "sample_count": sample_count,
        "observation_count": observation_count,
        "window_size": ROBUST_STATS_WINDOW_SIZE,
        "min_samples": ROBUST_STATS_MIN_SAMPLES,
        "low_confidence": low_confidence,
        "median": _rounded_vector(median),
        "mad": _rounded_vector(mad),
        "covariance": _rounded_matrix(np.asarray(covariance, dtype=float)),
        "covariance_method": covariance_method,
        "covariance_sample_count": covariance_sample_count,
        "covariance_observation_count": covariance_observation_count,
        "samples": samples,
    }


def _robust_covariance(matrix: np.ndarray, *, low_confidence: bool) -> tuple[np.ndarray, str]:
    if not low_confidence:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                covariance = MinCovDet(random_state=0).fit(matrix).covariance_
            if _is_valid_covariance(covariance):
                return covariance, "min_cov_det"
        except (ValueError, np.linalg.LinAlgError):
            pass

    if len(matrix) >= 2:
        try:
            covariance = LedoitWolf().fit(matrix).covariance_
            if _is_valid_covariance(covariance):
                return covariance, "ledoit_wolf"
        except (ValueError, np.linalg.LinAlgError):
            pass

    return _diagonal_covariance(matrix), "diagonal"


def _is_valid_covariance(covariance: np.ndarray) -> bool:
    covariance = np.asarray(covariance, dtype=float)
    return (
        covariance.shape == (len(FEATURE_NAMES), len(FEATURE_NAMES))
        and np.isfinite(covariance).all()
        and np.linalg.matrix_rank(covariance) == len(FEATURE_NAMES)
    )


def _diagonal_covariance(matrix: np.ndarray) -> np.ndarray:
    feature_count = len(FEATURE_NAMES)
    if len(matrix) >= 2:
        variances = np.var(matrix, axis=0, ddof=1)
    else:
        variances = np.zeros(feature_count)
    return np.diag(np.maximum(variances, ROBUST_STATS_DIAGONAL_FLOOR))


def _numeric_feature(value: Any) -> float:
    try:
        numeric = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return numeric if math.isfinite(numeric) else 0.0


def _rounded_vector(values: np.ndarray) -> list[float]:
    return [round(float(value), 8) for value in values]


def _rounded_matrix(values: np.ndarray) -> list[list[float]]:
    return [_rounded_vector(row) for row in values]


def _detect_deviation(baseline: dict[str, Any], event: AgentEvent) -> dict[str, Any]:
    event_count = int(baseline.get("event_count") or 0)
    if event_count < MIN_EVENTS_FOR_DEVIATION:
        return {"is_deviating": False, "score": 0.0, "reasons": ["cold_start"]}

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

    score = round(min(score, 1.0), 4)
    return {"is_deviating": score >= 0.5, "score": score, "reasons": reasons}


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
