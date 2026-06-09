import base64
import secrets

from kya.receipts.canonical import canonical_json, canonical_sha256
from kya.receipts.receipt import build_receipt, verify_receipt
from kya.receipts.signing import load_signing_key


def _seed() -> str:
    return base64.b64encode(secrets.token_bytes(32)).decode("ascii")


def test_canonical_json_is_deterministic():
    left = {"b": [2, 1], "a": {"z": True}}
    right = {"a": {"z": True}, "b": [2, 1]}

    assert canonical_json(left) == canonical_json(right)
    assert canonical_sha256(left) == canonical_sha256(right)


def test_build_receipt_signs_and_verifies():
    signing_key = load_signing_key(_seed())

    receipt = build_receipt(
        agent_id=7,
        action_payload={"tx_hash": "0xabc", "value": 1.25},
        decision={"trust_score": 91, "risk_factors": [], "shap_top": [], "confidence": 0.8},
        signals_fired=["kya_new_counterparty", "kya_new_counterparty"],
        previous_hash=None,
        signing_key=signing_key,
        receipt_id="receipt-1",
        created_at="2026-01-01T00:00:00Z",
    )

    assert receipt["signals_fired"] == ["kya_new_counterparty"]
    assert verify_receipt(receipt)["valid"] is True


def test_verify_receipt_rejects_tampering():
    receipt = build_receipt(
        agent_id=7,
        action_payload={"tx_hash": "0xabc"},
        decision={"trust_score": 91, "risk_factors": [], "shap_top": [], "confidence": 0.8},
        signals_fired=[],
        previous_hash=None,
        signing_key=load_signing_key(_seed()),
    )
    receipt["decision"]["trust_score"] = 10

    verification = verify_receipt(receipt)

    assert verification["valid"] is False
    assert verification["hash_valid"] is False
