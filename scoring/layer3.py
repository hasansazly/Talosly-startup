"""Layer 3 ML ensemble for transaction exploit routing.

Railway-safe build: only numpy + scikit-learn are required. The ensemble keeps
the 3-model architecture without xgboost, shap, or joblib:

1. Isolation Forest        - unsupervised anomaly score
2. Gradient Boosting (GBM) - supervised binary classifier
3. Bayesian Updater        - sequential prior x likelihood

The public output is a calibrated score in [0, 1]. Scores >= 0.55 escalate to
Layer 4; lower scores are stored and skipped.
"""

from __future__ import annotations

import json
import logging
import math
import os
import pickle
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier, IsolationForest
from sklearn.linear_model import LogisticRegression

from backend.config import settings

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
ESCALATION_THRESHOLD = settings.layer3_escalation_threshold
MODEL_DIR = Path(settings.layer3_model_dir)


def _env_bool(key: str, default: bool) -> bool:
    value = os.environ.get(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _current_threshold() -> float:
    value = os.environ.get("LAYER3_ESCALATION_THRESHOLD")
    if value is not None:
        try:
            return float(value)
        except ValueError:
            logger.warning("Invalid LAYER3_ESCALATION_THRESHOLD=%r; using settings value", value)
    return float(settings.layer3_escalation_threshold)


@dataclass
class EnsembleResult:
    """Layer 3 routing result for one transaction."""

    tx_hash: str
    ensemble_score: float
    confidence_low: float
    confidence_high: float
    escalate_to_llm: bool
    isolation_score: float
    gbm_prob: float
    bayesian_prob: float
    shap_top: list[dict[str, Any]]
    latency_ms: float
    mode: str = "ml"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class IsolationForestModel:
    """sklearn IsolationForest wrapper returning anomaly scores in [0, 1]."""

    def __init__(
        self,
        n_estimators: int = 200,
        contamination: float = 0.01,
        random_state: int = 42,
    ) -> None:
        self.model = IsolationForest(
            n_estimators=n_estimators,
            contamination=contamination,
            random_state=random_state,
            n_jobs=-1,
        )
        self._fitted = False

    def fit(self, X: np.ndarray) -> None:
        self.model.fit(X)
        self._fitted = True
        logger.info("IsolationForest fitted on %d samples", len(X))

    def score(self, x: np.ndarray) -> float:
        if not self._fitted:
            raise RuntimeError("IsolationForest not fitted.")
        raw = float(self.model.decision_function(x.reshape(1, -1))[0])
        return round(float(np.clip(0.5 - raw, 0.0, 1.0)), 4)

    def save(self, path: Path) -> None:
        path.write_bytes(pickle.dumps(self.model))

    def load(self, path: Path) -> None:
        self.model = pickle.loads(path.read_bytes())
        self._fitted = True


class GBMModel:
    """sklearn GradientBoostingClassifier with lightweight permutation SHAP."""

    def __init__(
        self,
        n_estimators: int = 200,
        max_depth: int = 5,
        learning_rate: float = 0.05,
        random_state: int = 42,
    ) -> None:
        self.model = GradientBoostingClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            subsample=0.8,
            random_state=random_state,
        )
        self._feature_means: np.ndarray | None = None
        self._fitted = False

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        self.model.fit(X, y)
        self._feature_means = X.mean(axis=0)
        self._fitted = True
        logger.info("GBM fitted on %d samples (%d positives)", len(y), int(y.sum()))

    def predict_proba(self, x: np.ndarray) -> float:
        if not self._fitted:
            raise RuntimeError("GBM not fitted.")
        return round(float(self.model.predict_proba(x.reshape(1, -1))[0, 1]), 4)

    def permutation_shap(self, x: np.ndarray, top_n: int = 3) -> list[dict[str, Any]]:
        if not self._fitted or self._feature_means is None:
            return []

        baseline_prob = self.predict_proba(x)
        contributions = []
        for index, feature_name in enumerate(FEATURE_NAMES):
            x_masked = x.copy()
            x_masked[index] = self._feature_means[index]
            masked_prob = self.predict_proba(x_masked)
            shap_value = round(baseline_prob - masked_prob, 4)
            contributions.append((feature_name, float(x[index]), shap_value))

        contributions.sort(key=lambda item: abs(item[2]), reverse=True)
        return [
            {"feature": name, "value": round(value, 4), "shap": shap_value}
            for name, value, shap_value in contributions[:top_n]
        ]

    def save(self, path: Path) -> None:
        path.write_bytes(pickle.dumps({"model": self.model, "means": self._feature_means}))

    def load(self, path: Path) -> None:
        payload = pickle.loads(path.read_bytes())
        self.model = payload["model"]
        self._feature_means = payload["means"]
        self._fitted = True


class BayesianUpdater:
    """Sequential Bayesian updates using log-odds."""

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

    def _active_signals(self, features: dict[str, Any]) -> list[str]:
        signals = []
        if float(features.get("graph_centrality") or 0) > 0.30:
            signals.append("graph_centrality_high")
        if float(features.get("velocity") or 0) > 5.0:
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
        signals = self._active_signals(features)

        for signal in signals:
            p_exploit, p_normal = self.LIKELIHOODS[signal]
            log_odds += math.log(p_exploit / p_normal)

        posterior = 1 / (1 + math.exp(-log_odds))
        n_eff = max(len(signals), 1)
        margin = 1.96 * math.sqrt(posterior * (1 - posterior) / n_eff)
        return (
            round(posterior, 4),
            round(max(posterior - margin, 0.0), 4),
            round(min(posterior + margin, 1.0), 4),
        )


class PlattScaler:
    """Logistic calibration with a weighted-average fallback."""

    WEIGHTS = np.array([0.25, 0.50, 0.25])

    def __init__(self) -> None:
        self._lr: LogisticRegression | None = None

    def fit(self, scores: np.ndarray, labels: np.ndarray) -> None:
        self._lr = LogisticRegression(C=1.0, max_iter=500)
        self._lr.fit(scores, labels)
        logger.info("PlattScaler fitted on %d samples", len(labels))

    def calibrate(self, if_score: float, gbm_prob: float, bayes_prob: float) -> float:
        raw_scores = np.array([[if_score, gbm_prob, bayes_prob]])
        if self._lr is not None:
            return round(float(self._lr.predict_proba(raw_scores)[0, 1]), 4)
        return round(float(np.dot(self.WEIGHTS, raw_scores[0])), 4)

    def save(self, path: Path) -> None:
        if self._lr is not None:
            path.write_bytes(pickle.dumps(self._lr))

    def load(self, path: Path) -> None:
        self._lr = pickle.loads(path.read_bytes())


class HeuristicLayer3Scorer:
    """Pure-Python fallback scorer with the same output shape as the ML path."""

    def __init__(self, base_rate: float = 0.001) -> None:
        self.bayesian = BayesianUpdater(base_rate=base_rate)

    def score(self, tx_hash: str, features: dict[str, Any]) -> EnsembleResult:
        started = time.perf_counter()
        clean_features = {name: features.get(name, 0.0) for name in FEATURE_NAMES}

        isolation_score = self._anomaly_score(clean_features)
        gbm_prob = self._signal_score(clean_features)
        bayesian_prob, confidence_low, confidence_high = self.bayesian.compute(clean_features)
        ensemble_score = round((0.25 * isolation_score) + (0.50 * gbm_prob) + (0.25 * bayesian_prob), 4)

        confidence_low = round(max(min(confidence_low, ensemble_score - 0.02), 0.0), 4)
        confidence_high = round(min(max(confidence_high, ensemble_score + 0.02), 1.0), 4)

        return EnsembleResult(
            tx_hash=tx_hash,
            ensemble_score=ensemble_score,
            confidence_low=confidence_low,
            confidence_high=confidence_high,
            escalate_to_llm=ensemble_score >= _current_threshold(),
            isolation_score=isolation_score,
            gbm_prob=gbm_prob,
            bayesian_prob=bayesian_prob,
            shap_top=self._top_signals(clean_features),
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            mode="heuristic",
        )

    def _anomaly_score(self, features: dict[str, Any]) -> float:
        age_days = float(features.get("wallet_age_days") or 365)
        signals = [
            min(float(features.get("graph_centrality") or 0) / 0.8, 1.0),
            min(float(features.get("velocity") or 0) / 20.0, 1.0),
            min(float(features.get("pool_drain_ratio") or 0) / 0.5, 1.0),
            min(float(features.get("flash_loan_fingerprint") or 0), 1.0),
            float(bool(features.get("tornado_tagged", False))),
            max(0.0, min((float(features.get("calldata_entropy") or 0) - 4.0) / 3.5, 1.0)),
            max(0.0, min(float(features.get("gas_anomaly_zscore") or 0) / 20.0, 1.0)),
            max(0.0, 1.0 - age_days / 30.0),
        ]
        return round(sum(signals) / len(signals), 4)

    def _signal_score(self, features: dict[str, Any]) -> float:
        weighted_score = 0.0
        total_weight = 0.0

        def add(value: float, weight: float) -> None:
            nonlocal weighted_score, total_weight
            weighted_score += min(max(value, 0.0), 1.0) * weight
            total_weight += weight

        age_days = float(features.get("wallet_age_days") or 365)
        add(float(features.get("flash_loan_fingerprint") or 0), 0.25)
        add(float(features.get("pool_drain_ratio") or 0) / 0.5, 0.20)
        add(float(bool(features.get("tornado_tagged", False))), 0.15)
        add(float(features.get("velocity") or 0) / 20.0, 0.12)
        add(1.0 - age_days / 30.0, 0.10)
        add((float(features.get("calldata_entropy") or 0) - 4.0) / 3.5, 0.08)
        add(float(features.get("gas_anomaly_zscore") or 0) / 20.0, 0.06)
        add(float(features.get("graph_centrality") or 0) / 0.8, 0.04)
        return round(weighted_score / total_weight if total_weight else 0.0, 4)

    def _top_signals(self, features: dict[str, Any]) -> list[dict[str, Any]]:
        age_days = float(features.get("wallet_age_days") or 365)
        contributions = [
            ("flash_loan_fingerprint", float(features.get("flash_loan_fingerprint") or 0), float(features.get("flash_loan_fingerprint") or 0) * 0.25),
            ("pool_drain_ratio", float(features.get("pool_drain_ratio") or 0), float(features.get("pool_drain_ratio") or 0) * 0.20),
            ("tornado_tagged", float(bool(features.get("tornado_tagged", False))), float(bool(features.get("tornado_tagged", False))) * 0.15),
            ("velocity", float(features.get("velocity") or 0), min(float(features.get("velocity") or 0) / 20.0, 1.0) * 0.12),
            ("wallet_age_days", age_days, max(0.0, 1.0 - age_days / 30.0) * 0.10),
        ]
        contributions.sort(key=lambda item: abs(item[2]), reverse=True)
        return [
            {"feature": name, "value": round(value, 4), "shap": round(shap_value, 4)}
            for name, value, shap_value in contributions[:3]
        ]


class Layer3MLEnsemble:
    """Public interface for Layer 3 training, persistence, and inference."""

    def __init__(
        self,
        base_rate: float = 0.001,
        model_dir: Path | None = None,
        bootstrap_if_missing: bool = True,
        enable_ml: bool | None = None,
    ) -> None:
        self.if_model = IsolationForestModel()
        self.gbm = GBMModel()
        self.bayesian = BayesianUpdater(base_rate=base_rate)
        self.platt = PlattScaler()
        self.heuristic = HeuristicLayer3Scorer(base_rate=base_rate)
        self.model_dir = Path(model_dir or os.environ.get("LAYER3_MODEL_DIR") or settings.layer3_model_dir)
        self._ready = False
        self.mode = "ml"

        ml_enabled = _env_bool("ENABLE_LAYER3_ML", settings.enable_layer3_ml) if enable_ml is None else enable_ml
        if not ml_enabled:
            self.mode = "heuristic"
            self._ready = True
            logger.info("Layer 3 ML disabled; using heuristic mode.")
            return

        if self._model_files_exist():
            try:
                self.load_models()
            except Exception as exc:
                self.mode = "heuristic"
                self._ready = True
                logger.warning("Layer 3 model load failed; using heuristic mode. error=%s", exc)
        elif bootstrap_if_missing:
            self.bootstrap_synthetic()
        else:
            self.mode = "heuristic"
            self._ready = True
            logger.warning("Layer 3 model files missing in %s; using heuristic mode.", self.model_dir)

    def fit(
        self,
        X_normal: np.ndarray,
        X_labelled: np.ndarray,
        y_labelled: np.ndarray,
        X_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
    ) -> None:
        self.if_model.fit(X_normal)
        self.gbm.fit(X_labelled, y_labelled)

        if X_val is not None and y_val is not None and len(set(y_val.tolist())) >= 2:
            self.platt.fit(self._raw_scores_batch(X_val), y_val)
        elif X_val is not None and y_val is not None:
            logger.warning("Skipping Platt calibration because validation data has one class.")

        self.mode = "ml"
        self._ready = True
        logger.info("Layer 3 training complete.")

    def bootstrap_synthetic(self) -> None:
        """Train an in-memory bootstrap model so fresh deploys can score safely."""
        X_normal, X_labelled, y_labelled = _make_synthetic_data()
        self.fit(X_normal, X_labelled, y_labelled)
        self.mode = "ml"
        logger.info("Layer 3 bootstrapped with synthetic training data.")

    def _raw_scores_batch(self, X: np.ndarray) -> np.ndarray:
        output = []
        for x in X:
            features = dict(zip(FEATURE_NAMES, x, strict=True))
            output.append(
                [
                    self.if_model.score(x),
                    self.gbm.predict_proba(x),
                    self.bayesian.compute(features)[0],
                ]
            )
        return np.array(output)

    def score(self, tx_hash: str, features: dict[str, Any]) -> EnsembleResult:
        if self.mode == "heuristic":
            return self.heuristic.score(tx_hash, features)

        if not self._ready:
            raise RuntimeError("Layer 3 models are not loaded or fitted.")

        started = time.perf_counter()
        clean_features = {name: features.get(name, 0.0) for name in FEATURE_NAMES}
        x = self._to_array(clean_features)

        isolation_score = self.if_model.score(x)
        gbm_prob = self.gbm.predict_proba(x)
        bayesian_prob, confidence_low, confidence_high = self.bayesian.compute(clean_features)
        ensemble_score = self.platt.calibrate(isolation_score, gbm_prob, bayesian_prob)

        confidence_low = round(max(min(confidence_low, ensemble_score - 0.02), 0.0), 4)
        confidence_high = round(min(max(confidence_high, ensemble_score + 0.02), 1.0), 4)

        return EnsembleResult(
            tx_hash=tx_hash,
            ensemble_score=ensemble_score,
            confidence_low=confidence_low,
            confidence_high=confidence_high,
            escalate_to_llm=ensemble_score >= _current_threshold(),
            isolation_score=isolation_score,
            gbm_prob=gbm_prob,
            bayesian_prob=bayesian_prob,
            shap_top=self.gbm.permutation_shap(x),
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            mode=self.mode,
        )

    @staticmethod
    def _to_array(features: dict[str, Any]) -> np.ndarray:
        return np.array(
            [
                features.get("graph_centrality", 0.0),
                features.get("velocity", 0.0),
                features.get("pool_drain_ratio", 0.0),
                features.get("flash_loan_fingerprint", 0.0),
                features.get("wallet_age_days", 0.0),
                float(features.get("tornado_tagged", False)),
                features.get("calldata_entropy", 0.0),
                features.get("gas_anomaly_zscore", 0.0),
            ],
            dtype=np.float32,
        )

    def _model_files_exist(self) -> bool:
        return (self.model_dir / "isolation_forest.pkl").exists() and (self.model_dir / "gbm.pkl").exists()

    def save_models(self) -> None:
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.if_model.save(self.model_dir / "isolation_forest.pkl")
        self.gbm.save(self.model_dir / "gbm.pkl")
        self.platt.save(self.model_dir / "platt_scaler.pkl")
        logger.info("Models saved to %s", self.model_dir)

    def load_models(self) -> None:
        self.if_model.load(self.model_dir / "isolation_forest.pkl")
        self.gbm.load(self.model_dir / "gbm.pkl")
        platt_path = self.model_dir / "platt_scaler.pkl"
        if platt_path.exists():
            self.platt.load(platt_path)
        self.mode = "ml"
        self._ready = True
        logger.info("Models loaded from %s", self.model_dir)


def _make_synthetic_data(
    n_normal: int = 2000,
    n_exploit: int = 100,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)

    X_normal = np.column_stack(
        [
            rng.beta(1, 5, n_normal),
            rng.exponential(0.5, n_normal),
            rng.beta(1, 20, n_normal),
            rng.beta(1, 15, n_normal),
            rng.exponential(300, n_normal),
            rng.binomial(1, 0.02, n_normal),
            rng.normal(3.2, 0.6, n_normal),
            rng.normal(0, 1, n_normal),
        ]
    ).astype(np.float32)

    X_exploit = np.column_stack(
        [
            rng.beta(5, 1, n_exploit),
            rng.uniform(8, 30, n_exploit),
            rng.uniform(0.4, 0.99, n_exploit),
            rng.uniform(0.6, 1.0, n_exploit),
            rng.uniform(0, 30, n_exploit),
            rng.binomial(1, 0.6, n_exploit),
            rng.uniform(5.5, 7.5, n_exploit),
            rng.uniform(5, 50, n_exploit),
        ]
    ).astype(np.float32)

    n_neg = n_exploit * 10
    X_labelled = np.vstack([X_normal[:n_neg], X_exploit])
    y_labelled = np.array([0] * n_neg + [1] * n_exploit)
    return X_normal, X_labelled, y_labelled


_default_layer3: Layer3MLEnsemble | None = None


def _get_default_layer3() -> Layer3MLEnsemble:
    global _default_layer3
    if _default_layer3 is None:
        _default_layer3 = Layer3MLEnsemble(bootstrap_if_missing=False)
    return _default_layer3


def score_transaction(tx_hash: str, features: dict[str, Any]) -> dict[str, Any]:
    """Score one transaction through the module-level Layer 3 scorer."""
    return _get_default_layer3().score(tx_hash, features).to_dict()


def active_mode() -> str:
    """Return the current module-level Layer 3 mode: ``ml`` or ``heuristic``."""
    return _get_default_layer3().mode


def reload_models() -> str:
    """Reload the module-level scorer and return its active mode."""
    global _default_layer3
    _default_layer3 = Layer3MLEnsemble(bootstrap_if_missing=False)
    logger.info("Layer 3 reloaded; mode=%s", _default_layer3.mode)
    return _default_layer3.mode


if __name__ == "__main__":
    from sklearn.model_selection import train_test_split

    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    print("=== Layer 3 - Railway-safe build (numpy + scikit-learn only) ===\n")

    X_normal, X_labelled, y_labelled = _make_synthetic_data()
    X_train, X_val, y_train, y_val = train_test_split(
        X_labelled,
        y_labelled,
        test_size=0.20,
        stratify=y_labelled,
        random_state=42,
    )

    layer3 = Layer3MLEnsemble(bootstrap_if_missing=False)
    layer3.fit(X_normal, X_train, y_train, X_val, y_val)
    layer3.save_models()

    layer3_reloaded = Layer3MLEnsemble(bootstrap_if_missing=False)
    layer3_reloaded.load_models()

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

    exploit_result = layer3_reloaded.score("0xdeadbeef", exploit_features)
    normal_result = layer3_reloaded.score("0xcafebabe", normal_features)

    print("\n--- Exploit tx ---")
    print(json.dumps(exploit_result.to_dict(), indent=2))
    print("\n--- Normal tx ---")
    print(json.dumps(normal_result.to_dict(), indent=2))

    print("\n=== Routing ===")
    for result in [exploit_result, normal_result]:
        route = "-> Layer 4 (LLM oracle)" if result.escalate_to_llm else "-> store & skip"
        print(
            f"  {result.tx_hash}  score={result.ensemble_score:.3f}  "
            f"CI=[{result.confidence_low:.3f}, {result.confidence_high:.3f}]  "
            f"{route}  ({result.latency_ms} ms)"
        )
