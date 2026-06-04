"""Conformal anomaly confidence from per-agent base score calibration."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from kya.config import kya_settings


@dataclass(frozen=True)
class ConformalSignal:
    p_value: float
    confidence: float
    provisional: bool
    anomalous: bool
    calibration: dict[str, Any]
    enabled: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_conformal_signal(
    anomaly_score: float,
    conformal_calib: dict[str, Any] | None = None,
) -> ConformalSignal:
    """Compute a conformal p-value and update the normal-score calibration set."""
    calibration = _normalize_calibration(conformal_calib)
    if not kya_settings.kya_enable_conformal:
        return ConformalSignal(1.0, 0.0, True, False, calibration, False)

    score = _clamp(_numeric(anomaly_score))
    scores = calibration["scores"]
    sample_count = len(scores)
    min_samples = max(int(kya_settings.kya_conformal_min_samples), 1)
    window_size = max(int(kya_settings.kya_conformal_window_size), 1)
    alpha = _clamp(_numeric(kya_settings.kya_conformal_alpha))
    p_value = (1 + sum(1 for value in scores if value >= score)) / (1 + sample_count)
    provisional = sample_count < min_samples
    anomalous = not provisional and p_value <= alpha

    if provisional or not anomalous:
        scores = [*scores, score][-window_size:]

    return ConformalSignal(
        p_value=round(p_value, 8),
        confidence=round(1.0 - p_value, 8),
        provisional=provisional,
        anomalous=anomalous,
        calibration={
            "scores": scores,
            "sample_count": len(scores),
        },
        enabled=True,
    )


def _normalize_calibration(value: dict[str, Any] | None) -> dict[str, Any]:
    calibration = value if isinstance(value, dict) else {}
    scores = [_clamp(_numeric(score)) for score in calibration.get("scores") or []]
    window_size = max(int(kya_settings.kya_conformal_window_size), 1)
    scores = scores[-window_size:]
    return {
        "scores": scores,
        "sample_count": len(scores),
    }


def _numeric(value: Any) -> float:
    try:
        numeric = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return numeric if math.isfinite(numeric) else 0.0


def _clamp(value: float) -> float:
    return min(max(value, 0.0), 1.0)


__all__ = ["ConformalSignal", "compute_conformal_signal"]
