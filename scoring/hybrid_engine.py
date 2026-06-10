"""Hybrid ML + GPT scoring engine for Talosly Stage 1."""

from __future__ import annotations

import json
import math
import os
import random
import statistics
from dataclasses import dataclass
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv() -> bool:
        return False

from scoring.cost_tracker import CostTracker
from scoring.oracle_response import OracleRiskResponse, action_for_score, confidence_from_interval


FEATURES = (
    "tx_value",
    "gas_used",
    "gas_price",
    "tx_frequency_1hr",
    "tx_frequency_24hr",
    "unique_counterparties",
    "contract_age_days",
)
ENSEMBLE_WEIGHTS = {
    "isolation_forest": 0.35,
    "lstm": 0.40,
    "bayesian": 0.25,
}


@dataclass(frozen=True)
class ModelSignals:
    """Raw hybrid model outputs before GPT reconciliation."""

    anomaly_score: float
    drain_velocity_score: float
    bayesian_risk: float
    bayesian_deviation: float
    composite_score: int
    interval: list[int]


class HybridScoringEngine:
    """Stateless ensemble scorer that gates GPT-4o mini usage."""

    def __init__(
        self,
        *,
        cost_tracker: CostTracker | None = None,
        ml_gate_threshold: int | None = None,
        confidence_gate: int | None = None,
    ) -> None:
        load_dotenv()
        self.cost_tracker = cost_tracker or CostTracker()
        self.ml_gate_threshold = ml_gate_threshold if ml_gate_threshold is not None else _env_int("ML_GATE_THRESHOLD", 65)
        self.confidence_gate = confidence_gate if confidence_gate is not None else _env_int("ML_CONFIDENCE_GATE", 20)

    def score(
        self,
        tx_data: dict[str, Any],
        protocol_history: list[dict[str, Any]],
        *,
        protocol_name: str = "Unknown Protocol",
        protocol_address: str = "global",
        days_monitored: int | None = None,
    ) -> OracleRiskResponse:
        """Score one transaction with ML first and GPT only when the gate opens."""
        days = days_monitored if days_monitored is not None else _days_monitored(protocol_history)
        warning: str | None = None
        try:
            signals = self.compute_signals(tx_data, protocol_history)
        except Exception as exc:
            warning = f"ML pipeline failed; attempted GPT-only fallback: {exc.__class__.__name__}"
            return self._gpt_only_fallback(
                tx_data,
                protocol_name=protocol_name,
                protocol_address=protocol_address,
                days_monitored=days,
                warning=warning,
            )

        interval_width = max(0, signals.interval[1] - signals.interval[0])
        should_call_gpt = (
            _env_bool("LAYER4_LLM_ENABLED", False)
            and (signals.composite_score > self.ml_gate_threshold or interval_width > self.confidence_gate)
        )

        gpt_reasoning: str | None = None
        final_score = signals.composite_score
        gpt_consulted = False
        if should_call_gpt:
            try:
                gpt_score, gpt_reasoning, usage = self._call_gpt(
                    signals=signals,
                    protocol_name=protocol_name,
                    days_monitored=days,
                )
                gpt_consulted = True
                final_score = _clamp_int(gpt_score * 0.6 + signals.composite_score * 0.4)
                self.cost_tracker.log_gpt_call(
                    protocol=protocol_address or protocol_name,
                    input_tokens=usage[0],
                    output_tokens=usage[1],
                    score_delta=final_score - signals.composite_score,
                )
            except Exception as exc:
                gpt_consulted = True
                warning = f"GPT gate opened but GPT call failed; using ML score: {exc.__class__.__name__}"
        else:
            self.cost_tracker.log_saved_call(protocol=protocol_address or protocol_name)

        return OracleRiskResponse(
            score=final_score,
            confidence=confidence_from_interval(signals.interval),
            interval=signals.interval,
            p_exploit=signals.drain_velocity_score,
            signals={
                "anomaly": signals.anomaly_score,
                "drain_velocity": signals.drain_velocity_score,
                "bayesian_deviation": signals.bayesian_deviation,
            },
            gpt_consulted=gpt_consulted,
            gpt_reasoning=gpt_reasoning,
            action=action_for_score(final_score),
            warning=warning,
        )

    def compute_signals(self, tx_data: dict[str, Any], protocol_history: list[dict[str, Any]]) -> ModelSignals:
        """Compute Isolation Forest, LSTM, Bayesian, and bootstrap ensemble signals."""
        anomaly_score = isolation_forest_score(tx_data, protocol_history)
        drain_velocity_score = lstm_drain_velocity_score(tx_data, protocol_history)
        bayesian_risk, bayesian_deviation = bayesian_risk_update(tx_data, protocol_history)
        composite = combine_scores(anomaly_score, drain_velocity_score, bayesian_risk)
        interval = bootstrap_interval(anomaly_score, drain_velocity_score, bayesian_risk)
        return ModelSignals(
            anomaly_score=anomaly_score,
            drain_velocity_score=drain_velocity_score,
            bayesian_risk=bayesian_risk,
            bayesian_deviation=bayesian_deviation,
            composite_score=composite,
            interval=interval,
        )

    def _call_gpt(
        self,
        *,
        signals: ModelSignals,
        protocol_name: str,
        days_monitored: int,
    ) -> tuple[int, str, tuple[int, int]]:
        """Consult GPT-4o mini and parse its JSON response."""
        from openai import OpenAI

        api_key = os.environ["OPENAI_API_KEY"]
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=150,
            temperature=0.1,
            messages=[
                {
                    "role": "system",
                    "content": "You are a DeFi security analyst. Respond only with JSON: {score: int, reasoning: str}",
                },
                {
                    "role": "user",
                    "content": (
                        f"ML signals — anomaly: {signals.anomaly_score:.2f}, "
                        f"drain_velocity: {signals.drain_velocity_score:.2f}, "
                        f"bayesian_risk: {signals.bayesian_risk:.2f}. "
                        f"Protocol: {protocol_name}, monitored for {days_monitored} days. "
                        f"ML composite score: {signals.composite_score}/100. "
                        "Return final risk score 0-100 and one-sentence reasoning."
                    ),
                },
            ],
        )
        parsed = json.loads(response.choices[0].message.content or "{}")
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        return _clamp_int(parsed.get("score", 0)), str(parsed.get("reasoning", ""))[:240], (input_tokens, output_tokens)

    def _gpt_only_fallback(
        self,
        tx_data: dict[str, Any],
        *,
        protocol_name: str,
        protocol_address: str,
        days_monitored: int,
        warning: str,
    ) -> OracleRiskResponse:
        """Fall back to GPT-only if the ML pipeline cannot produce signals."""
        fallback_signals = ModelSignals(0.0, 0.0, 0.0, 0.0, 50, [40, 60])
        if not _env_bool("LAYER4_LLM_ENABLED", False):
            return OracleRiskResponse(
                score=50,
                confidence=0.0,
                interval=[40, 60],
                p_exploit=0.0,
                signals={"anomaly": 0.0, "drain_velocity": 0.0, "bayesian_deviation": 0.0},
                gpt_consulted=False,
                gpt_reasoning=None,
                action=action_for_score(50),
                warning=warning,
            )
        try:
            gpt_score, gpt_reasoning, usage = self._call_gpt(
                signals=fallback_signals,
                protocol_name=protocol_name,
                days_monitored=days_monitored,
            )
            self.cost_tracker.log_gpt_call(
                protocol=protocol_address or protocol_name,
                input_tokens=usage[0],
                output_tokens=usage[1],
                score_delta=gpt_score - 50,
            )
            return OracleRiskResponse(
                score=gpt_score,
                confidence=0.4,
                interval=[max(0, gpt_score - 15), min(100, gpt_score + 15)],
                p_exploit=0.0,
                signals={"anomaly": 0.0, "drain_velocity": 0.0, "bayesian_deviation": 0.0},
                gpt_consulted=True,
                gpt_reasoning=gpt_reasoning,
                action=action_for_score(gpt_score),
                warning=warning,
            )
        except Exception as exc:
            return OracleRiskResponse(
                score=50,
                confidence=0.0,
                interval=[40, 60],
                p_exploit=0.0,
                signals={"anomaly": 0.0, "drain_velocity": 0.0, "bayesian_deviation": 0.0},
                gpt_consulted=True,
                gpt_reasoning=None,
                action="WARN",
                warning=f"{warning}; GPT fallback also failed: {exc.__class__.__name__}",
            )


def score(
    tx_data: dict[str, Any],
    protocol_history: list[dict[str, Any]],
    *,
    protocol_name: str = "Unknown Protocol",
    protocol_address: str = "global",
    days_monitored: int | None = None,
) -> dict[str, object]:
    """Convenience function returning the oracle response as a dict."""
    return HybridScoringEngine().score(
        tx_data,
        protocol_history,
        protocol_name=protocol_name,
        protocol_address=protocol_address,
        days_monitored=days_monitored,
    ).to_dict()


def isolation_forest_score(tx_data: dict[str, Any], protocol_history: list[dict[str, Any]]) -> float:
    """Return Isolation Forest anomaly score from 0-1, where >0.7 is anomalous."""
    baseline = _calibration_window(protocol_history)
    if len(baseline) < 20:
        return _robust_anomaly_score(tx_data, protocol_history)

    matrix = [_feature_row(row) for row in baseline]
    current = [_feature_row(tx_data)]
    try:
        from sklearn.ensemble import IsolationForest

        model = IsolationForest(contamination=0.03, random_state=42)
        model.fit(matrix)
        raw_score = -float(model.score_samples(current)[0])
        baseline_scores = [-float(item) for item in model.score_samples(matrix)]
        return _percentile_score(raw_score, baseline_scores)
    except Exception:
        return _robust_anomaly_score(tx_data, baseline)


def lstm_drain_velocity_score(tx_data: dict[str, Any], protocol_history: list[dict[str, Any]]) -> float:
    """Return LSTM drain velocity score from a rolling 60-transaction window."""
    sequence = (protocol_history + [tx_data])[-60:]
    if len(sequence) < 6:
        return 0.0
    try:
        import torch

        model = DrainVelocityLSTM()
        model.eval()
        tensor = torch.tensor([[_tx_value(row), _gas_used(row), _timestamp_delta(sequence, index)] for index, row in enumerate(sequence)], dtype=torch.float32)
        tensor = _normalize_tensor(tensor).unsqueeze(0)
        with torch.no_grad():
            score_value = torch.sigmoid(model(tensor)).item()
        heuristic = _drain_velocity_heuristic(sequence)
        return round(max(0.0, min(1.0, score_value * 0.35 + heuristic * 0.65)), 4)
    except Exception:
        return _drain_velocity_heuristic(sequence)


class DrainVelocityLSTM:
    """Two-layer LSTM architecture for drain velocity detection."""

    def __new__(cls) -> Any:
        """Create a torch module only when torch is available."""
        import torch

        class _TorchDrainVelocityLSTM(torch.nn.Module):
            """2-layer LSTM, hidden=64, dropout=0.2."""

            def __init__(self) -> None:
                super().__init__()
                self.lstm = torch.nn.LSTM(
                    input_size=3,
                    hidden_size=64,
                    num_layers=2,
                    dropout=0.2,
                    batch_first=True,
                )
                self.head = torch.nn.Linear(64, 1)

            def forward(self, sequence: Any) -> Any:
                """Run the LSTM and return one risk logit."""
                output, _ = self.lstm(sequence)
                return self.head(output[:, -1, :]).squeeze(-1)

        return _TorchDrainVelocityLSTM()


def bayesian_risk_update(tx_data: dict[str, Any], protocol_history: list[dict[str, Any]]) -> tuple[float, float]:
    """Update baseline prior risk with a log-odds likelihood ratio."""
    baseline = _last_days(protocol_history, days=30)
    if len(baseline) < 5:
        baseline = protocol_history[-100:]
    values = [_tx_value(row) for row in baseline] or [0.0]
    frequencies = [_frequency_1hr(row) for row in baseline] or [0.0]
    value_mean = statistics.fmean(values)
    value_std = statistics.pstdev(values) or 1.0
    freq_mean = statistics.fmean(frequencies)
    freq_std = statistics.pstdev(frequencies) or 1.0

    value_z = abs((_tx_value(tx_data) - value_mean) / value_std)
    freq_z = abs((_frequency_1hr(tx_data) - freq_mean) / freq_std)
    deviation = round(max(value_z, freq_z), 4)

    prior_probability = max(0.01, min(0.35, sum(1 for row in baseline if _tx_value(row) > value_mean + 3 * value_std) / max(len(baseline), 1)))
    prior_log_odds = math.log(prior_probability / (1.0 - prior_probability))
    likelihood_ratio = max(0.1, min(25.0, math.exp(min(deviation, 6.0) - 2.5)))
    posterior_log_odds = prior_log_odds + math.log(likelihood_ratio)
    posterior = 1.0 / (1.0 + math.exp(-posterior_log_odds))
    return round(max(0.0, min(1.0, posterior)), 4), deviation


def combine_scores(anomaly_score: float, drain_velocity_score: float, bayesian_risk: float) -> int:
    """Combine model signals with Talosly's configured ensemble weights."""
    weighted = (
        anomaly_score * ENSEMBLE_WEIGHTS["isolation_forest"]
        + drain_velocity_score * ENSEMBLE_WEIGHTS["lstm"]
        + bayesian_risk * ENSEMBLE_WEIGHTS["bayesian"]
    )
    return _clamp_int(weighted * 100)


def bootstrap_interval(anomaly_score: float, drain_velocity_score: float, bayesian_risk: float, samples: int = 100) -> list[int]:
    """Return [p5, p95] interval from 100 bootstrap ensemble samples."""
    rng = random.Random(42)
    values = []
    signals = [anomaly_score, drain_velocity_score, bayesian_risk]
    weights = list(ENSEMBLE_WEIGHTS.values())
    for _ in range(samples):
        jittered = [max(0.0, min(1.0, rng.choice(signals) + rng.gauss(0, 0.04))) for _ in signals]
        values.append(_clamp_int(sum(value * weight for value, weight in zip(jittered, weights)) * 100))
    values.sort()
    return [values[int(samples * 0.05)], values[int(samples * 0.95) - 1]]


def _feature_row(tx_data: dict[str, Any]) -> list[float]:
    """Extract the seven Isolation Forest features."""
    return [
        _tx_value(tx_data),
        _gas_used(tx_data),
        _gas_price(tx_data),
        _frequency_1hr(tx_data),
        _frequency_24hr(tx_data),
        _unique_counterparties(tx_data),
        _contract_age_days(tx_data),
    ]


def _calibration_window(protocol_history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Use the first 7 days of monitoring as the normal calibration baseline."""
    if not protocol_history:
        return []
    first_ts = _timestamp(protocol_history[0])
    if first_ts is None:
        return protocol_history[:500]
    cutoff = first_ts + 7 * 24 * 60 * 60
    return [row for row in protocol_history if (_timestamp(row) or first_ts) <= cutoff]


def _last_days(protocol_history: list[dict[str, Any]], *, days: int) -> list[dict[str, Any]]:
    """Return rows inside the latest rolling N-day window."""
    if not protocol_history:
        return []
    last_ts = _timestamp(protocol_history[-1])
    if last_ts is None:
        return protocol_history[-500:]
    cutoff = last_ts - days * 24 * 60 * 60
    return [row for row in protocol_history if (_timestamp(row) or last_ts) >= cutoff]


def _robust_anomaly_score(tx_data: dict[str, Any], baseline: list[dict[str, Any]]) -> float:
    """Fallback anomaly score using robust z-score style deviation."""
    if not baseline:
        return 0.0
    deviations = []
    for index, value in enumerate(_feature_row(tx_data)):
        series = [row[index] for row in [_feature_row(item) for item in baseline]]
        mean = statistics.fmean(series)
        std = statistics.pstdev(series) or 1.0
        deviations.append(abs((value - mean) / std))
    return round(max(0.0, min(1.0, max(deviations) / 6.0)), 4)


def _drain_velocity_heuristic(sequence: list[dict[str, Any]]) -> float:
    """Fast fallback for acceleration patterns before flash-loan-style drains."""
    values = [_tx_value(row) for row in sequence]
    gas_values = [_gas_used(row) for row in sequence]
    first_half = values[: len(values) // 2] or [0.0]
    second_half = values[len(values) // 2 :] or [0.0]
    value_acceleration = (statistics.fmean(second_half) - statistics.fmean(first_half)) / (statistics.pstdev(values) or 1.0)
    gas_acceleration = (gas_values[-1] - statistics.fmean(gas_values)) / (statistics.pstdev(gas_values) or 1.0)
    return round(max(0.0, min(1.0, (value_acceleration + gas_acceleration) / 8.0)), 4)


def _normalize_tensor(tensor: Any) -> Any:
    """Normalize a torch tensor feature-wise for LSTM inference."""
    mean = tensor.mean(dim=0, keepdim=True)
    std = tensor.std(dim=0, keepdim=True).clamp_min(1.0)
    return (tensor - mean) / std


def _percentile_score(value: float, baseline: list[float]) -> float:
    """Normalize a raw score by percentile position against baseline scores."""
    if not baseline:
        return 0.0
    count = sum(1 for item in baseline if value >= item)
    return round(max(0.0, min(1.0, count / len(baseline))), 4)


def _days_monitored(protocol_history: list[dict[str, Any]]) -> int:
    """Estimate days monitored from the first and last timestamp."""
    if len(protocol_history) < 2:
        return 0
    start = _timestamp(protocol_history[0])
    end = _timestamp(protocol_history[-1])
    if start is None or end is None:
        return 0
    return max(0, int((end - start) / 86400))


def _timestamp_delta(sequence: list[dict[str, Any]], index: int) -> float:
    """Return timestamp delta for one sequence row."""
    if index == 0:
        return 0.0
    current = _timestamp(sequence[index])
    previous = _timestamp(sequence[index - 1])
    if current is None or previous is None:
        return 60.0
    return max(0.0, current - previous)


def _timestamp(row: dict[str, Any]) -> float | None:
    """Extract a timestamp from common field names."""
    for key in ("timestamp", "created_at_ts", "block_timestamp", "seen_at"):
        value = row.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _tx_value(row: dict[str, Any]) -> float:
    """Extract transaction value."""
    return _float(row.get("tx_value", row.get("value_eth", row.get("value", 0.0))))


def _gas_used(row: dict[str, Any]) -> float:
    """Extract gas used."""
    return _float(row.get("gas_used", row.get("gas", 0.0)))


def _gas_price(row: dict[str, Any]) -> float:
    """Extract gas price."""
    return _float(row.get("gas_price", row.get("gasPrice", row.get("max_fee_per_gas", 0.0))))


def _frequency_1hr(row: dict[str, Any]) -> float:
    """Extract one-hour transaction frequency."""
    return _float(row.get("tx_frequency_1hr", row.get("calls_per_hour", row.get("call_frequency", 0.0))))


def _frequency_24hr(row: dict[str, Any]) -> float:
    """Extract 24-hour transaction frequency."""
    return _float(row.get("tx_frequency_24hr", row.get("calls_per_day", 0.0)))


def _unique_counterparties(row: dict[str, Any]) -> float:
    """Extract unique counterparty count."""
    return _float(row.get("unique_counterparties", row.get("counterparties", 0.0)))


def _contract_age_days(row: dict[str, Any]) -> float:
    """Extract contract age in days."""
    return _float(row.get("contract_age_days", row.get("contract_age", 0.0)))


def _float(value: Any) -> float:
    """Convert a value to float with hex-string support."""
    if value is None:
        return 0.0
    if isinstance(value, str):
        try:
            if value.startswith("0x"):
                return float(int(value, 16))
            return float(value)
        except ValueError:
            return 0.0
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return numeric if math.isfinite(numeric) else 0.0


def _clamp_int(value: Any) -> int:
    """Clamp a number to an integer risk score between 0 and 100."""
    return max(0, min(100, int(round(_float(value)))))


def _env_int(name: str, default: int) -> int:
    """Read an integer environment variable."""
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
