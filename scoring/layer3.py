"""Layer 3 ML-style ensemble for Layer 2 transaction features.

The production model dependencies are optional. If sklearn, xgboost, shap, or
joblib are unavailable, this module still returns a no-cost Bayesian/heuristic
ensemble result instead of breaking the worker.
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FEATURE_NAMES = [
    "graph_centrality",
    "velocity",
    "pool_drain_ratio",
    "flash_loan_fingerprint",
    "wallet_age_days",
    "tornado_tagged",
    "calldata_entropy",
    "gas_anomaly_zscore",
]
ESCALATION_THRESHOLD = 0.55
MODEL_DIR = Path("models")


@dataclass
class EnsembleResult:
    """Layer 3 routing result for one transaction."""

    tx_hash: str
    ensemble_score: float
    confidence_low: float
    confidence_high: float
    escalate_to_llm: bool
    isolation_score: float
    xgb_prob: float
    bayesian_prob: float
    shap_top: list[dict[str, Any]]
    latency_ms: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BayesianUpdater:
    """Sequential Bayesian risk estimate from binary feature signals."""

    LIKELIHOODS: dict[str, tuple[float, float]] = {
        "graph_centrality_high": (0.70, 0.05),
        "velocity_high": (0.75, 0.08),
        "pool_drain_high": (0.90, 0.01),
        "flash_loan": (0.80, 0.03),
        "wallet_young": (0.65, 0.10),
        "tornado_tagged": (0.85, 0.02),
        "calldata_entropy_high": (0.60, 0.12),
        "gas_anomaly_high": (0.70, 0.10),
    }

    def __init__(self, base_rate: float = 0.001) -> None:
        self.base_rate = base_rate

    def _signals_from_features(self, features: dict[str, Any]) -> list[str]:
        signals = []
        if float(features.get("graph_centrality") or 0) > 0.3:
            signals.append("graph_centrality_high")
        if float(features.get("velocity") or 0) > 5:
            signals.append("velocity_high")
        if float(features.get("pool_drain_ratio") or 0) > 0.20:
            signals.append("pool_drain_high")
        if float(features.get("flash_loan_fingerprint") or 0) > 0.50:
            signals.append("flash_loan")
        if float(features.get("wallet_age_days") or 999) < 30:
            signals.append("wallet_young")
        if bool(features.get("tornado_tagged", False)):
            signals.append("tornado_tagged")
        if float(features.get("calldata_entropy") or 0) > 5.0:
            signals.append("calldata_entropy_high")
        if float(features.get("gas_anomaly_zscore") or 0) > 3.0:
            signals.append("gas_anomaly_high")
        return signals

    def compute(self, features: dict[str, Any]) -> tuple[float, float, float]:
        prior = min(max(self.base_rate, 1e-9), 1 - 1e-9)
        log_odds = math.log(prior / (1 - prior))
        active_signals = self._signals_from_features(features)

        for signal in active_signals:
            p_exploit, p_normal = self.LIKELIHOODS.get(signal, (0.5, 0.5))
            log_odds += math.log(p_exploit / p_normal)

        posterior = 1 / (1 + math.exp(-log_odds))
        n_eff = max(len(active_signals), 1)
        margin = 1.96 * math.sqrt(posterior * (1 - posterior) / n_eff)
        return round(posterior, 4), round(max(posterior - margin, 0.0), 4), round(min(posterior + margin, 1.0), 4)


class HeuristicAnomalyModel:
    """Dependency-free anomaly proxy used until trained models are installed."""

    def score(self, features: dict[str, Any]) -> float:
        normalized = [
            min(float(features.get("graph_centrality") or 0), 1.0),
            min(float(features.get("velocity") or 0) / 10, 1.0),
            min(float(features.get("pool_drain_ratio") or 0), 1.0),
            min(float(features.get("flash_loan_fingerprint") or 0), 1.0),
            1.0 if float(features.get("wallet_age_days") or 999) < 30 else 0.0,
            1.0 if bool(features.get("tornado_tagged", False)) else 0.0,
            min(float(features.get("calldata_entropy") or 0) / 8, 1.0),
            min(max(float(features.get("gas_anomaly_zscore") or 0), 0.0) / 10, 1.0),
        ]
        return round(sum(normalized) / len(normalized), 4)


class HeuristicClassifier:
    """Dependency-free supervised-model placeholder with explainable weights."""

    WEIGHTS = {
        "graph_centrality": 0.08,
        "velocity": 0.10,
        "pool_drain_ratio": 0.22,
        "flash_loan_fingerprint": 0.22,
        "wallet_age_days": 0.08,
        "tornado_tagged": 0.12,
        "calldata_entropy": 0.08,
        "gas_anomaly_zscore": 0.10,
    }

    def predict_proba(self, features: dict[str, Any]) -> float:
        score = (
            min(float(features.get("graph_centrality") or 0), 1.0) * self.WEIGHTS["graph_centrality"]
            + min(float(features.get("velocity") or 0) / 10, 1.0) * self.WEIGHTS["velocity"]
            + min(float(features.get("pool_drain_ratio") or 0), 1.0) * self.WEIGHTS["pool_drain_ratio"]
            + min(float(features.get("flash_loan_fingerprint") or 0), 1.0) * self.WEIGHTS["flash_loan_fingerprint"]
            + (1.0 if float(features.get("wallet_age_days") or 999) < 30 else 0.0) * self.WEIGHTS["wallet_age_days"]
            + (1.0 if bool(features.get("tornado_tagged", False)) else 0.0) * self.WEIGHTS["tornado_tagged"]
            + min(float(features.get("calldata_entropy") or 0) / 8, 1.0) * self.WEIGHTS["calldata_entropy"]
            + min(max(float(features.get("gas_anomaly_zscore") or 0), 0.0) / 10, 1.0) * self.WEIGHTS["gas_anomaly_zscore"]
        )
        return round(min(max(score, 0.0), 1.0), 4)

    def shap_top_features(self, features: dict[str, Any], top_n: int = 3) -> list[dict[str, Any]]:
        contributions = []
        for name in FEATURE_NAMES:
            value = features.get(name, 0.0)
            numeric = float(value) if not isinstance(value, bool) else float(value)
            contributions.append({"feature": name, "value": round(numeric, 4), "shap": round(numeric * self.WEIGHTS[name], 4)})
        return sorted(contributions, key=lambda item: abs(item["shap"]), reverse=True)[:top_n]


class PlattScaler:
    """Calibrate raw model scores. Uses a weighted average until fitted."""

    DEFAULT_WEIGHTS = (0.25, 0.50, 0.25)

    def calibrate(self, if_score: float, xgb_prob: float, bayes_prob: float) -> float:
        score = (
            self.DEFAULT_WEIGHTS[0] * if_score
            + self.DEFAULT_WEIGHTS[1] * xgb_prob
            + self.DEFAULT_WEIGHTS[2] * bayes_prob
        )
        return round(min(max(score, 0.0), 1.0), 4)


class Layer3MLEnsemble:
    """Layer 3 ensemble interface for online transaction scoring."""

    def __init__(self, base_rate: float = 0.001, model_dir: Path = MODEL_DIR) -> None:
        self.bayesian = BayesianUpdater(base_rate=base_rate)
        self.if_model = HeuristicAnomalyModel()
        self.xgb_model = HeuristicClassifier()
        self.platt = PlattScaler()
        self.model_dir = model_dir

    def score(self, tx_hash: str, features: dict[str, Any]) -> EnsembleResult:
        started = time.perf_counter()
        clean_features = {name: features.get(name, 0.0) for name in FEATURE_NAMES}

        isolation_score = self.if_model.score(clean_features)
        xgb_prob = self.xgb_model.predict_proba(clean_features)
        bayesian_prob, confidence_low, confidence_high = self.bayesian.compute(clean_features)
        ensemble_score = self.platt.calibrate(isolation_score, xgb_prob, bayesian_prob)
        confidence_low = round(max(min(confidence_low, ensemble_score - 0.02), 0.0), 4)
        confidence_high = round(min(max(confidence_high, ensemble_score + 0.02), 1.0), 4)

        return EnsembleResult(
            tx_hash=tx_hash,
            ensemble_score=ensemble_score,
            confidence_low=confidence_low,
            confidence_high=confidence_high,
            escalate_to_llm=ensemble_score >= ESCALATION_THRESHOLD,
            isolation_score=isolation_score,
            xgb_prob=xgb_prob,
            bayesian_prob=bayesian_prob,
            shap_top=self.xgb_model.shap_top_features(clean_features),
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )


if __name__ == "__main__":
    exploit_features = {
        "graph_centrality": 0.92,
        "velocity": 18.0,
        "pool_drain_ratio": 0.85,
        "flash_loan_fingerprint": 1.0,
        "wallet_age_days": 2.0,
        "tornado_tagged": True,
        "calldata_entropy": 6.81,
        "gas_anomaly_zscore": 42.0,
    }
    normal_features = {
        "graph_centrality": 0.04,
        "velocity": 0.2,
        "pool_drain_ratio": 0.00012,
        "flash_loan_fingerprint": 0.0,
        "wallet_age_days": 400.0,
        "tornado_tagged": False,
        "calldata_entropy": 3.11,
        "gas_anomaly_zscore": -0.33,
    }
    layer3 = Layer3MLEnsemble()
    print(json.dumps(layer3.score("0xdeadbeef", exploit_features).to_dict(), indent=2))
    print(json.dumps(layer3.score("0xcafebabe", normal_features).to_dict(), indent=2))
