"""Ed25519-signed, SHA-256 hash-chained action receipts.

Each receipt covers one scored agent action. The chain is per-agent:
receipt N embeds the content_hash of receipt N-1 as prev_hash, giving
an append-only, tamper-evident audit log for every agent's decision history.

Key management
--------------
Set RECEIPT_SIGNING_KEY_HEX to a 64-hex-char (32-byte) Ed25519 seed to get
a stable key across restarts. If unset, an ephemeral key is generated at
startup — valid for a single process lifetime, not suitable for production.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

RECEIPT_VERSION = "kya-action-receipt/v1"

logger = logging.getLogger(__name__)

_signing_key: Ed25519PrivateKey | None = None


def _get_signing_key() -> Ed25519PrivateKey:
    global _signing_key
    if _signing_key is None:
        raw_hex = os.environ.get("RECEIPT_SIGNING_KEY_HEX", "")
        if len(raw_hex) == 64:
            try:
                _signing_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(raw_hex))
                logger.info("receipts.key.loaded_from_env")
                return _signing_key
            except Exception:
                logger.warning("receipts.key.invalid_env_hex — generating ephemeral key")
        else:
            logger.warning(
                "RECEIPT_SIGNING_KEY_HEX not set or invalid — using ephemeral key. "
                "Receipts will not be verifiable after process restart."
            )
        _signing_key = Ed25519PrivateKey.generate()
    return _signing_key


def get_public_key_hex() -> str:
    key = _get_signing_key()
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


def _canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()


def _hash_payload(payload: dict) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _sign(payload: dict) -> str:
    return _get_signing_key().sign(_canonical_json(payload)).hex()


def build_receipt(
    *,
    agent_id: int,
    action: str,
    trust_score: int,
    decision: str,
    risk_factors: list[str],
    shap_top: list[dict],
    confidence: float,
    prev_hash: str | None,
) -> dict[str, Any]:
    """Construct and sign one receipt. Returns the full receipt dict ready for DB insert."""
    payload: dict[str, Any] = {
        "version": RECEIPT_VERSION,
        "agent_id": agent_id,
        "prev_hash": prev_hash,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "trust_score": trust_score,
        "decision": decision,
        "risk_factors": risk_factors,
        "shap_top": shap_top,
        "confidence": confidence,
    }
    content_hash = _hash_payload(payload)
    signature = _sign(payload)
    return {
        "agent_id": agent_id,
        "payload": payload,
        "content_hash": content_hash,
        "prev_hash": prev_hash,
        "signature": signature,
    }


def verify_receipt(payload: dict, content_hash: str, signature_hex: str) -> tuple[bool, str]:
    """Verify hash integrity and Ed25519 signature. Returns (valid, reason)."""
    computed = _hash_payload(payload)
    if computed != content_hash:
        return False, f"hash_mismatch: computed={computed[:16]}… stored={content_hash[:16]}…"
    try:
        pub = _get_signing_key().public_key()
        pub.verify(bytes.fromhex(signature_hex), _canonical_json(payload))
    except InvalidSignature:
        return False, "signature_invalid"
    except Exception as exc:
        return False, f"verify_error: {exc}"
    return True, "ok"
