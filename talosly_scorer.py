"""Legacy standalone Stage 1 scorer.

Production code uses backend.services.scorer.TransactionScorer. This module is
kept only as an old standalone experiment/reference so importing runtime paths
does not accidentally depend on it.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

import numpy as np


FIELDS = ("tx_value", "gas_price", "call_frequency")


def _as_float(value: Any, default: float = 0.0) -> float:
    """Convert ints, floats, decimal strings, and hex strings into floats."""
    if value is None:
        return default
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        if math.isnan(float(value)) or math.isinf(float(value)):
            return default
        return float(value)
    if isinstance(value, str):
        try:
            if value.startswith("0x"):
                return float(int(value, 16))
            return float(value)
        except ValueError:
            return default
    return default


def _first_number(data: dict[str, Any], keys: tuple[str, ...], default: float = 0.0) -> float:
    """Return the first numeric value present under any candidate key."""
    for key in keys:
        if key in data:
            return _as_float(data.get(key), default)
    return default


def _tx_value(data: dict[str, Any]) -> float:
    """Extract transaction value in the best available units from tx data."""
    return _first_number(data, ("tx_value", "value_eth", "value", "amount", "amount_eth"))


def _gas_price(data: dict[str, Any]) -> float:
    """Extract gas price from common transaction field names."""
    return _first_number(data, ("gas_price", "gasPrice", "max_fee_per_gas", "maxFeePerGas"))


def _call_frequency(data: dict[str, Any]) -> float:
    """Extract call frequency from common field names."""
    return _first_number(data, ("call_frequency", "calls_per_minute", "callFrequency", "frequency"))


def _timestamp(data: dict[str, Any]) -> float | None:
    """Extract a timestamp-like value when present."""
    for key in ("timestamp", "created_at_ts", "block_timestamp", "seen_at"):
        value = data.get(key)
        parsed = _as_float(value, default=float("nan"))
        if not math.isnan(parsed):
            return parsed
    return None


def _time_delta_seconds(tx_data: dict[str, Any], protocol_history: list[dict[str, Any]]) -> float:
    """Return seconds since the previous transaction when timestamps are available."""
    explicit = _first_number(tx_data, ("time_delta_seconds", "timeDeltaSeconds"), default=float("nan"))
    if not math.isnan(explicit):
        return max(explicit, 0.0)

    current_ts = _timestamp(tx_data)
    if current_ts is None or not protocol_history:
        return 60.0

    previous_ts = _timestamp(protocol_history[-1])
    if previous_ts is None:
        return 60.0
    return max(current_ts - previous_ts, 0.0)


def _rolling_values(protocol_history: list[dict[str, Any]], field: str, limit: int) -> np.ndarray:
    """Build a numeric rolling history array for a supported field."""
    extractors = {
        "tx_value": _tx_value,
        "gas_price": _gas_price,
        "call_frequency": _call_frequency,
    }
    extractor = extractors[field]
    values = [extractor(row) for row in protocol_history[-limit:]]
    return np.asarray(values, dtype=float)


def _z_score(value: float, values: np.ndarray) -> float:
    """Calculate a rolling z-score, returning 0.0 for insufficient variance."""
    if values.size < 2:
        return 0.0
    std = float(np.std(values))
    if std == 0:
        return 0.0
    return abs((value - float(np.mean(values))) / std)


def _iqr_outlier(value: float, values: np.ndarray) -> bool:
    """Return True when value falls outside the 1.5x IQR fence."""
    if values.size < 4:
        return False
    q1, q3 = np.percentile(values, [25, 75])
    iqr = float(q3 - q1)
    if iqr == 0:
        return False
    lower = float(q1 - 1.5 * iqr)
    upper = float(q3 + 1.5 * iqr)
    return value < lower or value > upper


def calculate_anomaly_flags(tx_data: dict[str, Any], protocol_history: list[dict[str, Any]]) -> dict[str, bool]:
    """Run rolling z-score and IQR checks for value, gas, and frequency spikes."""
    checks = {
        "value_spike": ("tx_value", _tx_value(tx_data)),
        "gas_spike": ("gas_price", _gas_price(tx_data)),
        "freq_spike": ("call_frequency", _call_frequency(tx_data)),
    }

    flags: dict[str, bool] = {}
    for flag_name, (field, value) in checks.items():
        values = _rolling_values(protocol_history, field, limit=200)
        z_flag = _z_score(value, values) >= 3.0
        iqr_flag = _iqr_outlier(value, values)
        flags[flag_name] = bool(z_flag or iqr_flag)
    return flags


def _mean_std(values: np.ndarray) -> tuple[float, float]:
    """Return stable mean and std values for normalization."""
    if values.size == 0:
        return 0.0, 1.0
    mean = float(np.mean(values))
    std = float(np.std(values))
    return mean, std if std > 0 else 1.0


def _normalized(value: float, values: np.ndarray) -> float:
    """Normalize a value against historical mean/std."""
    mean, std = _mean_std(values)
    return (value - mean) / std


def _feature_vector(tx_data: dict[str, Any], protocol_history: list[dict[str, Any]]) -> list[float]:
    """Create the Isolation Forest feature vector for a transaction."""
    value_history = _rolling_values(protocol_history, "tx_value", limit=500)
    gas_history = _rolling_values(protocol_history, "gas_price", limit=500)
    return [
        _normalized(_tx_value(tx_data), value_history),
        _normalized(_gas_price(tx_data), gas_history),
        _time_delta_seconds(tx_data, protocol_history),
        _call_frequency(tx_data),
    ]


def calculate_isolation_score(tx_data: dict[str, Any], protocol_history: list[dict[str, Any]]) -> float:
    """Train a rolling Isolation Forest and return anomaly confidence from 0.0 to 1.0."""
    if len(protocol_history) < 20:
        return 0.0

    try:
        from sklearn.ensemble import IsolationForest
    except ImportError:
        return 0.0

    window = protocol_history[-500:]
    features = np.asarray([_feature_vector(row, window[:index]) for index, row in enumerate(window)], dtype=float)
    current = np.asarray([_feature_vector(tx_data, window)], dtype=float)

    if features.shape[0] < 20:
        return 0.0

    model = IsolationForest(contamination=0.01, random_state=42)
    model.fit(features)

    historical_scores = model.decision_function(features)
    current_score = float(model.decision_function(current)[0])
    anomaly_percentile = float(np.mean(historical_scores > current_score))
    return round(max(0.0, min(1.0, anomaly_percentile)), 4)


def build_claude_prompt(
    tx_data: dict[str, Any],
    anomaly_flags: dict[str, bool],
    isolation_score: float,
) -> str:
    """Build the enriched Claude prompt with pre-filter context."""
    return (
        "You are Talosly's DeFi transaction risk analyst.\n\n"
        "Raw tx data:\n"
        f"{json.dumps(tx_data, indent=2, sort_keys=True, default=str)}\n\n"
        "Layer 1 anomaly_flags:\n"
        f"{json.dumps(anomaly_flags, indent=2, sort_keys=True)}\n\n"
        "Layer 2 isolation_score:\n"
        f"{isolation_score:.4f}\n\n"
        "These signals suggest possible anomaly. Score 0–100. Be conservative — only score >70 if multiple independent signals align. Normal network congestion is NOT an exploit.\n\n"
        "Return ONLY JSON in this shape:\n"
        '{"final_score": 0, "reasoning": "one line"}'
    )


def _extract_text(response: Any) -> str:
    """Extract text from common Claude response shapes."""
    if isinstance(response, str):
        return response
    content = getattr(response, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if text is None and isinstance(item, dict):
                text = item.get("text")
            if text:
                parts.append(str(text))
        return "\n".join(parts)
    if isinstance(response, dict):
        if isinstance(response.get("content"), str):
            return str(response["content"])
        if isinstance(response.get("text"), str):
            return str(response["text"])
    return str(response)


def parse_claude_response(response: Any) -> tuple[int, str]:
    """Parse Claude output into a final score and one-line reasoning."""
    text = _extract_text(response).strip()
    data: dict[str, Any] = {}

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                data = {}

    score_value = data.get("final_score", data.get("score", data.get("risk_score")))
    if score_value is None:
        score_match = re.search(r"(?:final_score|score|risk_score)\D+(\d{1,3})", text, flags=re.IGNORECASE)
        score_value = score_match.group(1) if score_match else 0

    final_score = int(max(0, min(100, round(_as_float(score_value)))))
    reasoning = str(data.get("reasoning", data.get("reason", ""))).strip()
    if not reasoning:
        reasoning = "Claude returned a score without structured reasoning."
    reasoning = " ".join(reasoning.split())
    return final_score, reasoning[:240]


def _call_claude(claude_client: Any, prompt: str) -> Any:
    """Call a passed Claude-style client without creating or configuring it."""
    messages = [{"role": "user", "content": prompt}]

    if hasattr(claude_client, "messages") and hasattr(claude_client.messages, "create"):
        return claude_client.messages.create(
            model="claude-3-5-sonnet-latest",
            max_tokens=300,
            messages=messages,
        )

    if hasattr(claude_client, "chat") and hasattr(claude_client.chat, "completions"):
        return claude_client.chat.completions.create(
            messages=messages,
            max_tokens=300,
        )

    if callable(claude_client):
        return claude_client(prompt)

    raise TypeError("claude_client must expose messages.create(), chat.completions.create(), or be callable")


def score_transaction(
    tx_data: dict,
    protocol_history: list[dict],
    claude_client: Any,
) -> dict[str, int | str | bool | float | dict[str, bool]]:
    """Score a transaction with statistical and Isolation Forest filters before Claude."""
    anomaly_flags = calculate_anomaly_flags(tx_data, protocol_history)
    isolation_score = calculate_isolation_score(tx_data, protocol_history)
    has_anomaly_flag = any(anomaly_flags.values())

    if not has_anomaly_flag and isolation_score < 0.4:
        return {
            "final_score": 15,
            "reasoning": "Skipped Claude: no rolling z-score, IQR, or Isolation Forest anomaly detected.",
            "skipped_claude": True,
            "anomaly_flags": anomaly_flags,
            "isolation_score": isolation_score,
        }

    prompt = build_claude_prompt(tx_data, anomaly_flags, isolation_score)
    try:
        response = _call_claude(claude_client, prompt)
        final_score, reasoning = parse_claude_response(response)
    except Exception as exc:
        final_score = int(min(isolation_score * 100, 65))
        reasoning = f"Claude failed; capped fallback score from Isolation Forest: {exc}"

    return {
        "final_score": final_score,
        "reasoning": reasoning,
        "skipped_claude": False,
        "anomaly_flags": anomaly_flags,
        "isolation_score": isolation_score,
    }
