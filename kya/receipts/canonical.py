"""Deterministic JSON helpers for receipt hashing."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any


def normalize_for_json(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): normalize_for_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize_for_json(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        normalize_for_json(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def canonical_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


__all__ = ["canonical_bytes", "canonical_json", "canonical_sha256", "normalize_for_json"]
