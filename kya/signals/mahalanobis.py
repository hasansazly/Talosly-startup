"""Robust Mahalanobis anomaly signal for per-agent feature profiles."""

from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from scipy.stats import chi2

REGULARIZATION = 1e-8
MAD_SCALE = 1.4826


@dataclass(frozen=True)
class MahalanobisSignal:
    probability: float
    distance_squared: float
    confidence: str
    method: str
    enabled: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_mahalanobis_signal(
    feature_vector: dict[str, Any],
    robust_stats: dict[str, Any],
) -> MahalanobisSignal:
    """Return a gated anomaly probability from an agent's robust feature profile."""
    if not _env_bool("KYA_ENABLE_MAHALANOBIS", False):
        return MahalanobisSignal(0.0, 0.0, "low", "disabled", False)

    feature_names = [str(name) for name in robust_stats.get("feature_names") or []]
    median = _vector(robust_stats.get("median"), len(feature_names))
    if not feature_names or median is None:
        return MahalanobisSignal(0.0, 0.0, "low", "unavailable", True)

    current = np.asarray([_numeric(feature_vector.get(name, 0.0)) for name in feature_names], dtype=float)
    delta = current - median

    if bool(robust_stats.get("low_confidence", True)):
        distance_squared = _per_feature_distance_squared(delta, robust_stats.get("mad"))
        return _result(distance_squared, len(feature_names), confidence="low", method="mad_fallback")

    covariance = _matrix(robust_stats.get("covariance"), len(feature_names))
    if covariance is None:
        distance_squared = _per_feature_distance_squared(delta, robust_stats.get("mad"))
        return _result(distance_squared, len(feature_names), confidence="low", method="mad_fallback")

    regularized = covariance + np.eye(len(feature_names)) * REGULARIZATION
    inverse_covariance = np.linalg.pinv(regularized, hermitian=True)
    distance_squared = max(float(delta.T @ inverse_covariance @ delta), 0.0)
    method = "regularized_pinv" if np.linalg.matrix_rank(covariance) < len(feature_names) else "pinv"
    return _result(distance_squared, len(feature_names), confidence="high", method=method)


def _per_feature_distance_squared(delta: np.ndarray, mad_value: Any) -> float:
    mad = _vector(mad_value, len(delta))
    if mad is None:
        return 0.0
    scale = np.maximum(mad * MAD_SCALE, REGULARIZATION)
    return max(float(np.sum(np.square(delta / scale))), 0.0)


def _result(distance_squared: float, degrees_of_freedom: int, *, confidence: str, method: str) -> MahalanobisSignal:
    probability = float(chi2.cdf(distance_squared, df=degrees_of_freedom))
    if not math.isfinite(probability):
        probability = 0.0
    return MahalanobisSignal(
        probability=round(min(max(probability, 0.0), 1.0), 8),
        distance_squared=round(max(distance_squared, 0.0), 8),
        confidence=confidence,
        method=method,
        enabled=True,
    )


def _vector(value: Any, expected_size: int) -> np.ndarray | None:
    try:
        vector = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        return None
    if vector.shape != (expected_size,) or not np.isfinite(vector).all():
        return None
    return vector


def _matrix(value: Any, expected_size: int) -> np.ndarray | None:
    try:
        matrix = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        return None
    if matrix.shape != (expected_size, expected_size) or not np.isfinite(matrix).all():
        return None
    return matrix


def _numeric(value: Any) -> float:
    try:
        numeric = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return numeric if math.isfinite(numeric) else 0.0


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


__all__ = ["MahalanobisSignal", "compute_mahalanobis_signal"]
