"""Minimal conformal calibration for KYA high-risk flags."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

DEFAULT_CACHE_PATH = Path(__file__).with_name("calibration_cache.json")
METHOD = "positive_recall_conformal"
COVERAGE_CLAIM = ">=95% marginal recall for labelled threats under exchangeability"


@dataclass(frozen=True)
class ConformalRiskResult:
    high_risk: bool
    threshold: float
    target_coverage: float
    coverage_claim: str
    exchangeability_required: bool
    calibration_size: int
    positive_calibration_size: int
    method: str = METHOD

    def to_dict(self) -> dict[str, Any]:
        return {
            "high_risk": self.high_risk,
            "threshold": self.threshold,
            "target_coverage": self.target_coverage,
            "coverage_claim": self.coverage_claim,
            "exchangeability_required": self.exchangeability_required,
            "calibration_size": self.calibration_size,
            "positive_calibration_size": self.positive_calibration_size,
            "method": self.method,
        }


class ConformalClassificationWrapper:
    """Calibrate a risk-probability cutoff with finite-sample conformal recall."""

    def __init__(self, target_coverage: float = 0.95) -> None:
        if not 0.0 < target_coverage < 1.0:
            raise ValueError("target_coverage must be between 0 and 1")
        self.target_coverage = float(target_coverage)
        self.alpha = 1.0 - self.target_coverage
        self.q_hat: float | None = None
        self.threshold: float | None = None
        self.calibration_size = 0
        self.positive_calibration_size = 0

    def calibrate(self, calibration_probabilities: Iterable[float], calibration_labels: Iterable[int]) -> float:
        probabilities = [float(value) for value in calibration_probabilities]
        labels = [int(value) for value in calibration_labels]
        if len(probabilities) != len(labels):
            raise ValueError("calibration_probabilities and calibration_labels must have equal length")

        positive_probabilities = [prob for prob, label in zip(probabilities, labels, strict=True) if label == 1]
        if not positive_probabilities:
            raise ValueError("at least one positive calibration label is required")

        non_conformity = sorted(1.0 - max(0.0, min(prob, 1.0)) for prob in positive_probabilities)
        k = math.ceil((len(non_conformity) + 1) * self.target_coverage)
        k = min(max(k, 1), len(non_conformity))

        self.q_hat = float(non_conformity[k - 1])
        self.threshold = round(float(max(0.0, min(1.0, 1.0 - self.q_hat))), 12)
        self.calibration_size = len(probabilities)
        self.positive_calibration_size = len(positive_probabilities)
        return self.threshold

    @classmethod
    def from_cache(cls, cache: dict[str, Any]) -> "ConformalClassificationWrapper":
        wrapper = cls(target_coverage=float(cache["target_coverage"]))
        wrapper.q_hat = float(cache["q_hat"])
        wrapper.threshold = float(cache["threshold"])
        wrapper.calibration_size = int(cache["calibration_size"])
        wrapper.positive_calibration_size = int(cache["positive_calibration_size"])
        if cache.get("method") != METHOD:
            raise ValueError(f"unsupported conformal method: {cache.get('method')}")
        if not 0.0 <= wrapper.threshold <= 1.0:
            raise ValueError("cached conformal threshold must be between 0 and 1")
        if wrapper.positive_calibration_size <= 0:
            raise ValueError("cached positive_calibration_size must be positive")
        return wrapper

    def predict_conformal_flag(self, risk_probability: float) -> ConformalRiskResult:
        if self.threshold is None:
            raise ValueError("Wrapper must be calibrated first")
        risk_probability = max(0.0, min(float(risk_probability), 1.0))
        return ConformalRiskResult(
            high_risk=risk_probability >= self.threshold,
            threshold=self.threshold,
            target_coverage=self.target_coverage,
            coverage_claim=COVERAGE_CLAIM,
            exchangeability_required=True,
            calibration_size=self.calibration_size,
            positive_calibration_size=self.positive_calibration_size,
        )


@lru_cache(maxsize=1)
def load_kya_conformal_wrapper(path: str | Path = DEFAULT_CACHE_PATH) -> ConformalClassificationWrapper:
    cache = json.loads(Path(path).read_text())
    return ConformalClassificationWrapper.from_cache(cache)


def evaluate_kya_risk_probability(risk_probability: float) -> dict[str, Any]:
    return load_kya_conformal_wrapper().predict_conformal_flag(risk_probability).to_dict()
