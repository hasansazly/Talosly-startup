#!/usr/bin/env python3
"""
KYA injection demo harness ("the Loom").

Run:
    python3 kya_injection_demo.py
    python3 kya_injection_demo.py --fast
    python3 kya_injection_demo.py --tamper
    python3 kya_injection_demo.py --no-color
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import random
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption

KEY_PATH = Path(".kya_demo_key")
LEDGER_PATH = Path("kya_receipts.jsonl")
GENESIS_HASH = "0" * 64

WEIGHTS = {
    "kya_new_counterparty": 0.30,
    "kya_unseen_selector": 0.25,
    "kya_value_z_score": 0.30,
    "kya_cadence_break": 0.15,
}

PLATT_A, PLATT_B = 8.0, 0.40
CUSUM_K = 0.35
CUSUM_H = 0.80
HIGH_RISK = 0.70
LEARN_MAX = 0.50
Z_FLOOR_N = 3


class C:
    USE = True

    @staticmethod
    def _w(code: str, s: str) -> str:
        return f"\033[{code}m{s}\033[0m" if C.USE else s

    @staticmethod
    def dim(s: str) -> str:
        return C._w("2", s)

    @staticmethod
    def red(s: str) -> str:
        return C._w("91", s)

    @staticmethod
    def grn(s: str) -> str:
        return C._w("92", s)

    @staticmethod
    def ylw(s: str) -> str:
        return C._w("93", s)

    @staticmethod
    def cyn(s: str) -> str:
        return C._w("96", s)

    @staticmethod
    def bold(s: str) -> str:
        return C._w("1", s)


PACE = 0.0


def beat(mult: float = 1.0) -> None:
    if PACE:
        time.sleep(PACE * mult)


@dataclass
class Action:
    t: float
    counterparty: str
    selector: str
    value: float
    label: str = ""


@dataclass
class FeatureState:
    """Causal profile state; only benign actions update the baseline."""

    seen_counterparties: set = field(default_factory=set)
    seen_selectors: set = field(default_factory=set)
    n: int = 0
    mean: float = 0.0
    m2: float = 0.0
    last_t: float | None = None
    ema_interval: float | None = None

    @property
    def std(self) -> float:
        return math.sqrt(self.m2 / (self.n - 1)) if self.n >= 2 else 0.0

    def note_time(self, t: float) -> None:
        self.last_t = t

    def learn(self, action: Action) -> None:
        self.seen_counterparties.add(action.counterparty)
        self.seen_selectors.add(action.selector)
        self.n += 1
        delta = action.value - self.mean
        self.mean += delta / self.n
        self.m2 += delta * (action.value - self.mean)
        if self.last_t is not None:
            interval = max(action.t - self.last_t, 1e-6)
            self.ema_interval = interval if self.ema_interval is None else 0.7 * self.ema_interval + 0.3 * interval


def compute_features(action: Action, state: FeatureState) -> dict:
    new_counterparty = 0.0 if action.counterparty in state.seen_counterparties else 1.0
    unseen_selector = 0.0 if action.selector in state.seen_selectors else 1.0
    z_score = (action.value - state.mean) / state.std if state.n >= Z_FLOOR_N and state.std > 1e-9 else 0.0

    if state.ema_interval and state.last_t is not None:
        interval = max(action.t - state.last_t, 1e-6)
        ratio = state.ema_interval / interval
        cadence_break = min(1.0, max(0.0, (ratio - 2.0) / 8.0))
    else:
        cadence_break = 0.0

    return {
        "kya_new_counterparty": new_counterparty,
        "kya_unseen_selector": unseen_selector,
        "kya_value_z_score": round(z_score, 3),
        "kya_cadence_break": round(cadence_break, 3),
    }


def _z_to_unit(z_score: float) -> float:
    return 1.0 / (1.0 + math.exp(-0.8 * (abs(z_score) - 3.0)))


def score_features(features: dict, jitter: float = 0.0) -> tuple[float, dict]:
    unit = {
        "kya_new_counterparty": features["kya_new_counterparty"],
        "kya_unseen_selector": features["kya_unseen_selector"],
        "kya_value_z_score": _z_to_unit(features["kya_value_z_score"]),
        "kya_cadence_break": features["kya_cadence_break"],
    }
    contrib = {key: round(WEIGHTS[key] * value, 4) for key, value in unit.items()}
    raw = min(1.0, max(0.0, sum(contrib.values()) + jitter))
    risk = 1.0 / (1.0 + math.exp(-PLATT_A * (raw - PLATT_B)))
    return round(risk, 4), contrib


class Cusum:
    def __init__(self, k: float = CUSUM_K, h: float = CUSUM_H) -> None:
        self.k = k
        self.h = h
        self.s = 0.0

    def update(self, value: float) -> tuple[float, bool]:
        self.s = max(0.0, self.s + (value - self.k))
        return round(self.s, 4), self.s >= self.h


def _raw_private_bytes(sk: Ed25519PrivateKey) -> bytes:
    return sk.private_bytes(encoding=Encoding.Raw, format=PrivateFormat.Raw, encryption_algorithm=NoEncryption())


def _raw_public_bytes(sk: Ed25519PrivateKey) -> bytes:
    return sk.public_key().public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)


def load_or_create_key() -> Ed25519PrivateKey:
    if KEY_PATH.exists():
        return Ed25519PrivateKey.from_private_bytes(KEY_PATH.read_bytes())
    sk = Ed25519PrivateKey.generate()
    KEY_PATH.write_bytes(_raw_private_bytes(sk))
    try:
        os.chmod(KEY_PATH, 0o600)
    except OSError:
        pass
    return sk


def pub_b64(sk: Ed25519PrivateKey) -> str:
    return base64.b64encode(_raw_public_bytes(sk)).decode("ascii")


def _canon(body: dict) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_receipt(sk: Ed25519PrivateKey, kind: str, prev_hash: str, payload: dict) -> dict:
    body = {"v": 1, "kind": kind, "issuer": pub_b64(sk), "prev_hash": prev_hash, "payload": payload}
    body_hash = hashlib.sha256(_canon(body)).hexdigest()
    sig = sk.sign(_canon(body))
    return {
        **body,
        "body_hash": body_hash,
        "sig": base64.b64encode(sig).decode("ascii"),
        "receipt_id": "KYA-" + body_hash[:12],
    }


def append_ledger(receipt: dict) -> None:
    with LEDGER_PATH.open("a") as fh:
        fh.write(json.dumps(receipt) + "\n")


def verify_chain(receipts: list[dict]) -> list[tuple[str, bool, str]]:
    out = []
    expected_prev = GENESIS_HASH
    for receipt in receipts:
        body = {key: receipt[key] for key in ("v", "kind", "issuer", "prev_hash", "payload")}
        canon = _canon(body)
        sig_ok = True
        try:
            pk = Ed25519PublicKey.from_public_bytes(base64.b64decode(receipt["issuer"]))
            pk.verify(base64.b64decode(receipt["sig"]), canon)
        except (InvalidSignature, Exception):
            sig_ok = False
        hash_ok = hashlib.sha256(canon).hexdigest() == receipt["body_hash"]
        link_ok = receipt["prev_hash"] == expected_prev
        ok = sig_ok and hash_ok and link_ok
        why = "ok" if ok else ",".join(item for item, good in [("sig", sig_ok), ("hash", hash_ok), ("link", link_ok)] if not good)
        out.append((receipt["receipt_id"], ok, why))
        expected_prev = receipt["body_hash"]
    return out


KNOWN_CPS = ["0xUniswapRouter", "0xAaveV3Pool", "0xTreasurySafe"]
KNOWN_SELS = ["swap", "deposit", "approve"]
ATTACKER = "0xDRAIN_a91f"
EVIL_SEL = "setApprovalForAll"


def benign_actions(rng: random.Random, n: int, start: float) -> list[Action]:
    actions = []
    t = start
    for _ in range(n):
        t += rng.uniform(45, 75)
        actions.append(Action(round(t, 2), rng.choice(KNOWN_CPS), rng.choice(KNOWN_SELS), round(rng.gauss(1.0, 0.15), 3), "normal"))
    return actions


def injection_burst(rng: random.Random, start_t: float, n: int = 5) -> list[Action]:
    actions = []
    t = start_t
    for _ in range(n):
        t += rng.uniform(0.004, 0.02)
        actions.append(Action(round(t, 4), ATTACKER, EVIL_SEL, round(rng.uniform(40, 80), 2), "injection"))
    return actions


def fmt_feats(features: dict) -> str:
    z_score = features["kya_value_z_score"]
    z_text = f"{z_score:>6}" if abs(z_score) < 100 else "  99+ "
    return (
        f"nc={int(features['kya_new_counterparty'])} us={int(features['kya_unseen_selector'])} "
        f"vz={z_text} cb={features['kya_cadence_break']:>4}"
    )


def line(action: Action, features: dict, risk: float, cusum_s: float, fired: bool, receipt_id: str | None) -> None:
    tag = C.red("CHANGE-POINT") if fired else (C.ylw("high") if risk >= HIGH_RISK else C.grn("ok"))
    counterparty = action.counterparty if action.counterparty in KNOWN_CPS else C.red(action.counterparty)
    selector = action.selector if action.selector in KNOWN_SELS else C.red(action.selector)
    risk_text = (C.red if risk >= HIGH_RISK else C.grn)(f"{risk:.2f}")
    cusum_text = (C.red if fired else C.dim)(f"{cusum_s:>5.2f}")
    receipt_text = ("  -> " + C.cyn(receipt_id)) if receipt_id else ""
    print(
        f"  t={action.t:>9.2f}  {counterparty:<22} {selector:<18} v={action.value:>6}  "
        f"[{fmt_feats(features)}]  risk={risk_text}  cusum={cusum_text}  {tag}{receipt_text}"
    )


def run(args: argparse.Namespace) -> None:
    global PACE
    PACE = 0.0 if args.fast else 0.18
    C.USE = args.force_color or ((not args.no_color) and sys.stdout.isatty())

    rng = random.Random(args.seed)
    LEDGER_PATH.unlink(missing_ok=True)
    sk = load_or_create_key()
    state = FeatureState()
    cusum = Cusum()
    receipts: list[dict] = []
    prev_hash = GENESIS_HASH

    print()
    print(C.bold("  KYA injection demo  -  Know-Your-Agent runtime monitor"))
    print(C.dim(f"  issuer {pub_b64(sk)[:24]}...   ledger {LEDGER_PATH}"))
    print(C.dim("  " + "-" * 98))

    for action in benign_actions(rng, n=10, start=0.0):
        state.learn(action)
        state.note_time(action.t)
    print(
        C.dim(
            f"  baseline learned: {len(state.seen_counterparties)} counterparties, "
            f"{len(state.seen_selectors)} selectors, "
            f"value mu={state.mean:.2f} sd={state.std:.2f}, "
            f"cadence~{state.ema_interval:.0f}s"
        )
    )

    anchor = build_receipt(
        sk,
        "session_anchor",
        prev_hash,
        {
            "agent_id": "agent://treasury-rebalancer",
            "baseline": {
                "counterparties": sorted(state.seen_counterparties),
                "selectors": sorted(state.seen_selectors),
                "value_mu": round(state.mean, 4),
                "value_sd": round(state.std, 4),
            },
            "detector": {"cusum_k": CUSUM_K, "cusum_h": CUSUM_H, "high_risk": HIGH_RISK},
            "ts": time.time(),
        },
    )
    append_ledger(anchor)
    receipts.append(anchor)
    prev_hash = anchor["body_hash"]
    print(C.dim(f"  anchored session  {anchor['receipt_id']}"))
    print(C.dim("  " + "-" * 98))

    normals = benign_actions(rng, n=8, start=state.last_t or 0.0)
    burst = injection_burst(rng, start_t=normals[-1].t + 60, n=5)
    stream = normals + burst

    print(C.grn("  > normal operation"))
    in_normal = True
    fired_once = False

    for action in stream:
        if in_normal and action.label == "injection":
            print()
            print(C.red("  > PROMPT INJECTION - agent hijacked, attempting drain"))
            in_normal = False

        features = compute_features(action, state)
        jitter = rng.uniform(0.0, 0.10) if action.label == "normal" else 0.0
        risk, contrib = score_features(features, jitter=jitter)
        cusum_s, fired = cusum.update(risk)

        receipt_id = None
        if fired and risk >= HIGH_RISK:
            receipt = build_receipt(
                sk,
                "detection",
                prev_hash,
                {
                    "agent_id": "agent://treasury-rebalancer",
                    "action": asdict(action),
                    "features": features,
                    "risk": risk,
                    "attribution": contrib,
                    "cusum": {"s": cusum_s, "h": CUSUM_H},
                    "verdict": "BLOCK",
                    "ts": time.time(),
                },
            )
            append_ledger(receipt)
            receipts.append(receipt)
            prev_hash = receipt["body_hash"]
            receipt_id = receipt["receipt_id"]
            fired_once = True

        line(action, features, risk, cusum_s, bool(receipt_id), receipt_id)

        if risk < LEARN_MAX:
            state.learn(action)
        state.note_time(action.t)
        beat(2.0 if receipt_id else 1.0)

    print(C.dim("  " + "-" * 98))
    if not fired_once:
        print(C.ylw("  no change-point fired - tune CUSUM_H / weights"))
        return

    print(C.bold("  > verifying receipt ledger (independent of emitter)"))
    beat(2)
    if args.tamper:
        victim = next(receipt for receipt in receipts if receipt["kind"] == "detection")
        before = victim["payload"]["action"]["value"]
        victim["payload"]["action"]["value"] = 0.01
        print(C.red(f"  ! tampered {victim['receipt_id']}: value {before} -> 0.01 (attacker tries to erase the drain)"))
    for receipt_id, ok, why in verify_chain(receipts):
        print(f"    {receipt_id}   " + (C.grn("valid") if ok else C.red(f"INVALID ({why})")))

    print(C.dim("  " + "-" * 98))
    n_detections = sum(1 for receipt in receipts if receipt["kind"] == "detection")
    print(
        f"  {C.bold('result:')} normal scored clean - injection tripped the change-point "
        f"- {n_detections} signed receipt(s) on the ledger"
    )
    print(C.dim(f"  ledger: {LEDGER_PATH.resolve()}"))
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="KYA injection demo harness")
    parser.add_argument("--fast", action="store_true")
    parser.add_argument("--tamper", action="store_true", help="alter a recorded receipt to prove tamper-evidence")
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument("--force-color", action="store_true")
    parser.add_argument("--seed", type=int, default=7)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
