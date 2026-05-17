"""Per-protocol model persistence for Talosly scoring models."""

from __future__ import annotations

import pickle
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_MODEL_ROOT = Path("models")


class ModelStore:
    """Persist and load per-protocol ML artifacts."""

    def __init__(self, root: Path | str = DEFAULT_MODEL_ROOT) -> None:
        self.root = Path(root)

    def protocol_dir(self, protocol_address: str) -> Path:
        """Return the filesystem directory for a protocol's models."""
        safe_address = "".join(char for char in protocol_address.lower() if char.isalnum() or char in {"x", "_", "-"})
        return self.root / (safe_address or "global")

    def isolation_forest_path(self, protocol_address: str) -> Path:
        """Return the configured Isolation Forest model path."""
        return self.protocol_dir(protocol_address) / "isolation_forest.pkl"

    def lstm_weights_path(self, protocol_address: str) -> Path:
        """Return the configured LSTM weights path."""
        return self.protocol_dir(protocol_address) / "lstm_weights.pt"

    def save_isolation_forest(self, protocol_address: str, model: Any) -> Path:
        """Persist an Isolation Forest model using joblib when available."""
        path = self.isolation_forest_path(protocol_address)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import joblib

            joblib.dump(model, path)
        except ImportError:
            with path.open("wb") as handle:
                pickle.dump(model, handle)
        return path

    def load_isolation_forest(self, protocol_address: str) -> Any | None:
        """Load an Isolation Forest model if one exists."""
        path = self.isolation_forest_path(protocol_address)
        if not path.exists():
            return None
        try:
            import joblib

            return joblib.load(path)
        except ImportError:
            with path.open("rb") as handle:
                return pickle.load(handle)

    def save_lstm_weights(self, protocol_address: str, model: Any) -> Path:
        """Persist LSTM weights with torch when available."""
        path = self.lstm_weights_path(protocol_address)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import torch

            torch.save(model.state_dict() if hasattr(model, "state_dict") else model, path)
        except ImportError:
            with path.open("wb") as handle:
                pickle.dump(model, handle)
        return path

    def should_use_global_baseline(self, transaction_count: int) -> bool:
        """Return True during cold start before protocol-specific training data exists."""
        return transaction_count < 500

    def should_retrain(self, protocol_address: str, interval_days: int = 7) -> bool:
        """Return True when model artifacts are missing or older than the retrain interval."""
        path = self.isolation_forest_path(protocol_address)
        if not path.exists():
            return True
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return datetime.now(timezone.utc) - modified >= timedelta(days=interval_days)
