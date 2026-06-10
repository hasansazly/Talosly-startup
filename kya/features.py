"""KYA feature vectors adapted to Talosly's existing Layer 3 schema."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from scoring.features import (
    CalldataEntropyExtractor,
    FlashLoanFingerprintExtractor,
    GasAnomalyExtractor,
    GraphFeatureExtractor,
    PoolDrainExtractor,
    WalletAgeExtractor,
)
from scoring.filters import PreFilterManager, TransactionPreFilter
from scoring.layer3 import FEATURE_NAMES

from kya.ingest import AgentEvent

_graph_extractor = GraphFeatureExtractor()
_pool_drain_extractor = PoolDrainExtractor()
_flash_loan_extractor = FlashLoanFingerprintExtractor()
_wallet_age_extractor = WalletAgeExtractor()
_calldata_entropy_extractor = CalldataEntropyExtractor()
_gas_anomaly_extractor = GasAnomalyExtractor()


def build_feature_vector(event: AgentEvent, baseline: dict[str, Any]) -> dict[str, Any]:
    """Build a Layer 3-compatible feature vector with KYA deviation context."""
    raw = _event_to_tx(event)
    graph_centrality, velocity = _graph_extractor.record_and_extract(raw)
    wallet_age_days, tornado_tagged = _wallet_age_extractor.extract(raw)
    calldata_entropy = _calldata_entropy_extractor.extract(raw)
    gas_anomaly_zscore = _gas_anomaly_extractor.record_and_extract(raw)

    deviation = baseline_deviation_features(event, baseline)

    graph_signal = 1.0 if deviation["new_counterparty"] else min(graph_centrality, 0.1)
    features = {
        "graph_centrality": graph_signal,
        "velocity": max(velocity, min(float(deviation["cadence_z_score"]), 20.0)),
        "pool_drain_ratio": max(_pool_drain_extractor.extract(raw), min(float(deviation["value_z_score"]) / 10, 1.0)),
        "flash_loan_fingerprint": max(
            _flash_loan_extractor.extract(raw),
            0.6 if deviation["unseen_selector"] else 0.0,
        ),
        "wallet_age_days": wallet_age_days,
        "tornado_tagged": tornado_tagged,
        "calldata_entropy": calldata_entropy,
        "gas_anomaly_zscore": min(
            max(gas_anomaly_zscore, float(deviation["value_z_score"]), float(deviation["cadence_z_score"])),
            50.0,
        ),
        "kya_new_counterparty": deviation["new_counterparty"],
        "kya_value_z_score": deviation["value_z_score"],
        "kya_cadence_break": deviation["cadence_break"],
        "kya_cadence_z_score": deviation["cadence_z_score"],
        "kya_off_hours": deviation["off_hours"],
        "kya_unseen_selector": deviation["unseen_selector"],
        "kya_sequence_anomaly": deviation["sequence_anomaly"],
    }
    return _layer3_compatible(features)


def baseline_deviation_features(event: AgentEvent, baseline: dict[str, Any]) -> dict[str, Any]:
    known_counterparties = {str(item).lower() for item in baseline.get("known_counterparties") or []}
    selectors_seen = {str(item).lower() for item in baseline.get("selectors_seen") or []}
    active_hours = {str(hour) for hour in (baseline.get("active_hours") or {}).keys()}

    counterparty = (event.counterparty or "").lower()
    selector = (event.selector or "").lower()
    value_z = _zscore(float(event.value or 0.0), baseline.get("value_stats") or {}, "mean", "std")
    cadence_z = _cadence_zscore(event, baseline.get("cadence_stats") or {})
    hour = str(_event_timestamp(event).hour)

    seq_anomaly = float((baseline.get("last_deviation") or {}).get("sequence_anomaly") or 0.0)
    return {
        "new_counterparty": bool(counterparty and counterparty not in known_counterparties),
        "value_z_score": round(value_z, 4),
        "cadence_break": cadence_z >= 3.0,
        "cadence_z_score": round(cadence_z, 4),
        "off_hours": bool(active_hours and hour not in active_hours),
        "unseen_selector": bool(selector and selector not in selectors_seen),
        "sequence_anomaly": round(seq_anomaly, 4),
    }


def _event_to_tx(event: AgentEvent) -> dict[str, Any]:
    raw = dict(event.raw or {})
    wallet = event.wallet
    counterparty = event.counterparty
    timestamp = _event_timestamp(event).timestamp()
    input_data = raw.get("input_data") or raw.get("input") or raw.get("calldata") or f"0x{event.selector}"
    if input_data == "0x" and event.selector:
        input_data = f"0x{event.selector}"

    tx = {
        **raw,
        "hash": raw.get("hash") or event.tx_hash,
        "tx_hash": event.tx_hash,
        "from": raw.get("from") or raw.get("from_address") or wallet,
        "from_address": raw.get("from_address") or raw.get("from") or wallet,
        "to": raw.get("to") or raw.get("to_address") or counterparty,
        "to_address": raw.get("to_address") or raw.get("to") or counterparty,
        "value_eth": event.value,
        "input": input_data,
        "input_data": input_data,
        "calldata": input_data,
        "timestamp": timestamp,
    }
    if "value_usd" not in tx:
        tx["value_usd"] = 0.0
    return tx


def _layer3_compatible(features: dict[str, Any]) -> dict[str, Any]:
    for name in FEATURE_NAMES:
        features.setdefault(name, False if name == "tornado_tagged" else 0.0)
    return features


def _cadence_zscore(event: AgentEvent, stats: dict[str, Any]) -> float:
    last_timestamp = _parse_timestamp(stats.get("last_timestamp"))
    if last_timestamp is None or int(stats.get("count") or 0) < 2:
        return 0.0
    interval = max((_event_timestamp(event) - last_timestamp).total_seconds(), 0.0)
    return _zscore(interval, stats, "mean_seconds", "std_seconds")


def _zscore(value: float, stats: dict[str, Any], mean_key: str, std_key: str) -> float:
    count = int(stats.get("count") or 0)
    std = float(stats.get(std_key) or 0.0)
    if count < 2 or std <= 0:
        return 0.0
    return abs(value - float(stats.get(mean_key) or 0.0)) / std


def _event_timestamp(event: AgentEvent) -> datetime:
    timestamp = event.timestamp
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


__all__ = [
    "PreFilterManager",
    "TransactionPreFilter",
    "baseline_deviation_features",
    "build_feature_vector",
]
