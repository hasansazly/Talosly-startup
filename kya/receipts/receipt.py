"""Build, hash, chain, sign, and verify KYA action receipts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from kya.receipts.canonical import canonical_sha256, normalize_for_json
from kya.receipts.signing import ReceiptSigningKey, verify_signature

RECEIPT_VERSION = "kya-action-receipt/v1"


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _hash_material(receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        key: receipt[key]
        for key in sorted(receipt)
        if key not in {"receipt_hash", "signature"}
    }


def hash_receipt(receipt: dict[str, Any]) -> str:
    return canonical_sha256(_hash_material(receipt))


def build_receipt(
    *,
    agent_id: int,
    action_payload: dict[str, Any],
    decision: dict[str, Any],
    signals_fired: list[str],
    previous_hash: str | None,
    signing_key: ReceiptSigningKey,
    receipt_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    receipt = {
        "id": receipt_id or str(uuid4()),
        "version": RECEIPT_VERSION,
        "agent_id": int(agent_id),
        "action_payload": normalize_for_json(action_payload),
        "decision": normalize_for_json(decision),
        "signals_fired": sorted(set(signals_fired)),
        "previous_hash": previous_hash,
        "public_key": signing_key.public_key,
        "created_at": created_at or _utc_now_text(),
    }
    receipt["receipt_hash"] = hash_receipt(receipt)
    receipt["signature"] = signing_key.sign(receipt["receipt_hash"].encode("ascii"))
    return receipt


def chain_receipt(receipt: dict[str, Any], previous_hash: str | None) -> dict[str, Any]:
    chained = dict(receipt)
    chained["previous_hash"] = previous_hash
    chained["receipt_hash"] = hash_receipt(chained)
    return chained


def verify_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    expected_hash = hash_receipt(receipt)
    hash_valid = expected_hash == receipt.get("receipt_hash")
    signature_valid = False
    if hash_valid and receipt.get("public_key") and receipt.get("signature") and receipt.get("receipt_hash"):
        signature_valid = verify_signature(
            str(receipt["public_key"]),
            str(receipt["signature"]),
            str(receipt["receipt_hash"]).encode("ascii"),
        )
    return {
        "valid": hash_valid and signature_valid,
        "hash_valid": hash_valid,
        "signature_valid": signature_valid,
        "expected_hash": expected_hash,
        "receipt_hash": receipt.get("receipt_hash"),
    }


__all__ = ["RECEIPT_VERSION", "build_receipt", "chain_receipt", "hash_receipt", "verify_receipt"]
