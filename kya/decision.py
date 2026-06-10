"""Shared allow / review / block decision policy."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

ALLOW, REVIEW, BLOCK = "allow", "review", "block"
_SEVERITY = {ALLOW: 0, REVIEW: 1, BLOCK: 2}

POLICY_VERSION = "1.0.0"


@dataclass(frozen=True)
class DecisionPolicy:
    block_below: int = 40
    review_below: int = 70
    signal_floor: dict = field(default_factory=lambda: {"changepoint": REVIEW})
    version: str = POLICY_VERSION


@dataclass
class Decision:
    decision: str
    reasons: list
    policy_version: str
    thresholds: dict

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "reasons": self.reasons,
            "policy_version": self.policy_version,
            "thresholds": self.thresholds,
        }


def _max(a: str, b: str) -> str:
    return a if _SEVERITY[a] >= _SEVERITY[b] else b


def decide(
    trust_score: int,
    signals_fired,
    policy: Optional[DecisionPolicy] = None,
) -> Decision:
    policy = policy or DecisionPolicy()
    signals = set(signals_fired or [])
    decision = ALLOW
    reasons: list = []

    if trust_score < policy.block_below:
        decision = _max(decision, BLOCK)
        reasons.append(f"trust_score {trust_score} < block_below {policy.block_below}")
    elif trust_score < policy.review_below:
        decision = _max(decision, REVIEW)
        reasons.append(f"trust_score {trust_score} < review_below {policy.review_below}")

    for sig, floor in policy.signal_floor.items():
        if sig in signals:
            decision = _max(decision, floor)
            reasons.append(f"signal '{sig}' fired, floor >= {floor}")

    if not reasons:
        reasons.append(
            f"trust_score {trust_score} >= review_below {policy.review_below}, "
            "no escalating signals"
        )

    return Decision(
        decision=decision,
        reasons=reasons,
        policy_version=policy.version,
        thresholds={
            "block_below": policy.block_below,
            "review_below": policy.review_below,
            "signal_floor": dict(policy.signal_floor),
        },
    )


def policy_from_env() -> DecisionPolicy:
    return DecisionPolicy(
        block_below=int(os.environ.get("DECISION_BLOCK_BELOW", "40")),
        review_below=int(os.environ.get("DECISION_REVIEW_BELOW", "70")),
    )


__all__ = [
    "ALLOW",
    "BLOCK",
    "REVIEW",
    "Decision",
    "DecisionPolicy",
    "decide",
    "policy_from_env",
]
