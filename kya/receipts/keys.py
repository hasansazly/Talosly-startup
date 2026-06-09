"""Lazy, cached receipt signing key access."""

from __future__ import annotations

from functools import lru_cache

from kya.receipts.signing import ReceiptSigningKey, load_signing_key


@lru_cache(maxsize=1)
def get_signing_key() -> ReceiptSigningKey:
    return load_signing_key()


__all__ = ["get_signing_key"]
