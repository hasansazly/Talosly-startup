"""Ed25519 signing helpers for action receipts."""

from __future__ import annotations

import base64
import binascii
import os
import secrets
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


@dataclass(frozen=True)
class ReceiptSigningKey:
    private_key: Ed25519PrivateKey

    @property
    def public_key_bytes(self) -> bytes:
        return self.private_key.public_key().public_bytes(
            encoding=Encoding.Raw,
            format=PublicFormat.Raw,
        )

    @property
    def public_key(self) -> str:
        return base64.b64encode(self.public_key_bytes).decode("ascii")

    def sign(self, payload: bytes) -> str:
        return base64.b64encode(self.private_key.sign(payload)).decode("ascii")


def _decode_seed(seed: str) -> bytes:
    value = seed.strip()
    try:
        decoded = bytes.fromhex(value)
    except ValueError:
        decoded = base64.b64decode(value, validate=True)
    if len(decoded) != 32:
        raise ValueError("RECEIPT_SIGNING_SEED must decode to exactly 32 bytes")
    return decoded


def load_signing_key(seed: str | None = None) -> ReceiptSigningKey:
    raw_seed = seed if seed is not None else os.getenv("RECEIPT_SIGNING_SEED")
    if not raw_seed:
        raise RuntimeError("RECEIPT_SIGNING_SEED is not configured")
    return ReceiptSigningKey(Ed25519PrivateKey.from_private_bytes(_decode_seed(raw_seed)))


def verify_signature(public_key: str, signature: str, payload: bytes) -> bool:
    try:
        public_key_bytes = base64.b64decode(public_key, validate=True)
        signature_bytes = base64.b64decode(signature, validate=True)
        Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(signature_bytes, payload)
    except (InvalidSignature, ValueError, binascii.Error):
        return False
    return True


def generate_seed() -> str:
    return base64.b64encode(secrets.token_bytes(32)).decode("ascii")


if __name__ == "__main__":
    print(generate_seed())


__all__ = ["ReceiptSigningKey", "generate_seed", "load_signing_key", "verify_signature"]
