"""Layer 2 feature engineering for transactions that survive Layer 1 filtering."""

from __future__ import annotations

import math
import statistics
import time
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class TxFeatures:
    """Feature vector produced by Layer 2 for downstream ML scoring."""

    graph_centrality: float = 0.0
    velocity: float = 0.0
    pool_drain_ratio: float = 0.0
    flash_loan_fingerprint: float = 0.0
    wallet_age_days: float = 0.0
    tornado_tagged: bool = False
    calldata_entropy: float = 0.0
    gas_anomaly_zscore: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GraphFeatureExtractor:
    """Approximate graph centrality and sender velocity with an in-memory window."""

    def __init__(self, window_seconds: int = 300) -> None:
        self.window = window_seconds
        self._call_log: dict[str, list[float]] = {}

    def _prune(self, now: float) -> None:
        cutoff = now - self.window
        for addr in list(self._call_log):
            self._call_log[addr] = [timestamp for timestamp in self._call_log[addr] if timestamp >= cutoff]
            if not self._call_log[addr]:
                del self._call_log[addr]

    def record_and_extract(self, tx: dict[str, Any]) -> tuple[float, float]:
        """Record a transaction and return graph centrality and velocity."""
        sender = str(tx.get("from") or tx.get("from_address") or "")
        now = float(tx.get("timestamp") or time.time())
        self._prune(now)

        log = self._call_log.setdefault(sender, [])
        log.append(now)

        velocity = len(log) / (self.window / 60)
        unique_targets = float(tx.get("unique_targets_touched") or 1)
        total_active = max(len(self._call_log), 1)
        graph_centrality = min(unique_targets / total_active, 1.0)
        return round(graph_centrality, 4), round(velocity, 4)


class PoolDrainExtractor:
    """Compute the fraction of known pool reserves moved by this transaction."""

    def extract(self, tx: dict[str, Any]) -> float:
        reserves = float(tx.get("pool_reserves_usd") or 0)
        value_usd = float(tx.get("value_usd") or 0)
        if reserves <= 0:
            return 0.0
        return round(min(value_usd / reserves, 1.0), 6)


class FlashLoanFingerprintExtractor:
    """Produce a 0-1 composite score indicating flash-loan behavior."""

    FLASH_SELECTORS = {
        "0x5cffe9de",
        "0xab9c4b5d",
        "0x23e30c8b",
        "0xd9d98ce4",
        "0x39941fa8",
    }

    def extract(self, tx: dict[str, Any]) -> float:
        score = 0.0
        weight = 0.25
        calldata = str(tx.get("calldata") or tx.get("input") or tx.get("input_data") or "0x")
        selector = calldata[:10].lower()

        if selector in self.FLASH_SELECTORS:
            score += weight
        if tx.get("same_block_repay", False):
            score += weight
        if int(tx.get("internal_calls_to_pool") or 0) > 1:
            score += weight

        reserves = float(tx.get("pool_reserves_usd") or 1)
        value = float(tx.get("value_usd") or 0)
        if reserves > 0 and value / reserves >= 0.10:
            score += weight

        return round(min(score, 1.0), 4)


class WalletAgeExtractor:
    """Extract sender age and mixer-funding flag from enrichment fields."""

    def extract(self, tx: dict[str, Any]) -> tuple[float, bool]:
        first_seen_ts = tx.get("sender_first_seen_ts")
        now = float(tx.get("timestamp") or time.time())

        if first_seen_ts is None:
            age_days = 0.0
        else:
            age_days = max((now - float(first_seen_ts)) / 86_400, 0.0)

        return round(age_days, 2), bool(tx.get("tornado_tagged", False))


class CalldataEntropyExtractor:
    """Compute Shannon entropy in bits per byte for calldata."""

    def extract(self, tx: dict[str, Any]) -> float:
        calldata = str(tx.get("calldata") or tx.get("input") or tx.get("input_data") or "0x")
        raw = calldata[2:] if calldata.startswith("0x") else calldata
        if not raw:
            return 0.0

        try:
            byte_vals = bytes.fromhex(raw)
        except ValueError:
            return 0.0
        if not byte_vals:
            return 0.0

        freq: dict[int, int] = {}
        for byte in byte_vals:
            freq[byte] = freq.get(byte, 0) + 1

        total = len(byte_vals)
        entropy = -sum((count / total) * math.log2(count / total) for count in freq.values())
        return round(entropy, 4)


class GasAnomalyExtractor:
    """Compute a rolling z-score for gas price."""

    def __init__(self, window: int = 200) -> None:
        self.window = window
        self._history: list[float] = []

    def record_and_extract(self, tx: dict[str, Any]) -> float:
        gas_price = float(tx.get("gas_price_gwei") or tx.get("gasPriceGwei") or 0)

        if len(self._history) >= 2:
            mean = statistics.mean(self._history)
            std = statistics.stdev(self._history) or 1e-9
            zscore = (gas_price - mean) / std
        else:
            zscore = 0.0

        self._history.append(gas_price)
        if len(self._history) > self.window:
            self._history.pop(0)

        return round(zscore, 4)


class Layer2FeatureEngineering:
    """Public interface for Layer 2 transaction feature engineering."""

    def __init__(self, velocity_window_seconds: int = 300, gas_window: int = 200) -> None:
        self.graph = GraphFeatureExtractor(window_seconds=velocity_window_seconds)
        self.pool_drain = PoolDrainExtractor()
        self.flash_loan = FlashLoanFingerprintExtractor()
        self.wallet = WalletAgeExtractor()
        self.calldata = CalldataEntropyExtractor()
        self.gas = GasAnomalyExtractor(window=gas_window)

    def process(self, tx: dict[str, Any]) -> TxFeatures:
        """Run all extractors and return a populated feature object."""
        normalized = self._normalize_tx(tx)
        graph_centrality, velocity = self.graph.record_and_extract(normalized)
        pool_drain_ratio = self.pool_drain.extract(normalized)
        flash_loan_fingerprint = self.flash_loan.extract(normalized)
        wallet_age_days, tornado_tagged = self.wallet.extract(normalized)
        calldata_entropy = self.calldata.extract(normalized)
        gas_anomaly_zscore = self.gas.record_and_extract(normalized)

        return TxFeatures(
            graph_centrality=graph_centrality,
            velocity=velocity,
            pool_drain_ratio=pool_drain_ratio,
            flash_loan_fingerprint=flash_loan_fingerprint,
            wallet_age_days=wallet_age_days,
            tornado_tagged=tornado_tagged,
            calldata_entropy=calldata_entropy,
            gas_anomaly_zscore=gas_anomaly_zscore,
        )

    @staticmethod
    def _normalize_tx(tx: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(tx)
        normalized.setdefault("from", tx.get("from_address"))
        normalized.setdefault("to", tx.get("to_address"))
        normalized.setdefault("calldata", tx.get("input_data") or tx.get("input") or "0x")
        normalized.setdefault("timestamp", time.time())
        if "value_usd" not in normalized and tx.get("value_eth") is not None:
            normalized["value_usd"] = 0.0
        return normalized


if __name__ == "__main__":
    import json

    layer2 = Layer2FeatureEngineering()
    exploit_tx = {
        "hash": "0xdeadbeef",
        "from": "0xattacker",
        "to": "0xpool",
        "calldata": "0x5cffe9de" + "a3f1b2c9d4e5f6a7b8c9d0e1f2a3b4c5" * 20,
        "timestamp": time.time(),
        "value_usd": 8_500_000,
        "pool_reserves_usd": 10_000_000,
        "same_block_repay": True,
        "internal_calls_to_pool": 3,
        "unique_targets_touched": 12,
        "sender_first_seen_ts": time.time() - 86_400 * 2,
        "tornado_tagged": True,
        "gas_price_gwei": 420.0,
    }
    for gwei in [25, 27, 26, 28, 24, 26, 25, 27]:
        layer2.gas.record_and_extract({"gas_price_gwei": gwei, "timestamp": time.time()})
    print(json.dumps(layer2.process(exploit_tx).to_dict(), indent=2))
