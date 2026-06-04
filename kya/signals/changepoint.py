"""Two-sided CUSUM detector for per-agent anomaly score streams."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from kya.config import kya_settings


@dataclass(frozen=True)
class ChangepointSignal:
    changepoint_score: float
    changepoint_detected: bool
    direction: str | None
    cusum_state: dict[str, Any]
    enabled: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_changepoint_signal(
    anomaly_score: float,
    cusum_state: dict[str, Any] | None = None,
) -> ChangepointSignal:
    """Update CUSUM accumulators for one normalized base anomaly score."""
    state = _normalize_state(cusum_state)
    if not kya_settings.kya_enable_changepoint:
        return ChangepointSignal(0.0, False, None, state, False)

    score = _clamp(_numeric(anomaly_score))
    drift = max(_numeric(kya_settings.kya_cusum_drift), 0.0)
    threshold = max(_numeric(kya_settings.kya_cusum_threshold), 1e-8)
    reference_mean = state["reference_mean"]
    count = int(state["count"])

    if reference_mean is None:
        state["reference_mean"] = score
        state["count"] = 1
        return ChangepointSignal(0.0, False, None, state, True)

    deviation = score - float(reference_mean)
    s_high = max(0.0, float(state["s_high"]) + deviation - drift)
    s_low = max(0.0, float(state["s_low"]) - deviation - drift)
    peak = max(s_high, s_low)
    detected = peak > threshold
    direction = "high" if detected and s_high >= s_low else "low" if detected else None
    changepoint_score = min(1.0, peak / threshold)

    if direction == "high":
        s_high = 0.0
    elif direction == "low":
        s_low = 0.0

    next_count = count + 1
    state.update(
        {
            "s_high": round(s_high, 8),
            "s_low": round(s_low, 8),
            "reference_mean": round(((float(reference_mean) * count) + score) / next_count, 8),
            "count": next_count,
        }
    )
    return ChangepointSignal(
        changepoint_score=round(changepoint_score, 8),
        changepoint_detected=detected,
        direction=direction,
        cusum_state=state,
        enabled=True,
    )


def _normalize_state(value: dict[str, Any] | None) -> dict[str, Any]:
    state = value if isinstance(value, dict) else {}
    reference_mean = state.get("reference_mean")
    reference = None if reference_mean is None else _clamp(_numeric(reference_mean))
    return {
        "s_high": max(_numeric(state.get("s_high")), 0.0),
        "s_low": max(_numeric(state.get("s_low")), 0.0),
        "reference_mean": reference,
        "count": max(int(_numeric(state.get("count"))), 0),
    }


def _numeric(value: Any) -> float:
    try:
        numeric = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return numeric if math.isfinite(numeric) else 0.0


def _clamp(value: float) -> float:
    return min(max(value, 0.0), 1.0)


__all__ = ["ChangepointSignal", "compute_changepoint_signal"]
