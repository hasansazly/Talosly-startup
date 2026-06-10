"""Warm-up guards for newly enabled KYA signals."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class WarmupPolicy:
    min_observations: int = 30


def policy_from_env() -> WarmupPolicy:
    return WarmupPolicy(
        min_observations=int(os.environ.get("SIGNAL_MIN_OBSERVATIONS", "30"))
    )


def is_warming_up(n_observations: int, policy: Optional[WarmupPolicy] = None) -> bool:
    policy = policy or WarmupPolicy()
    return n_observations < policy.min_observations


def covariance_is_usable(
    n_observations: int,
    n_features: int,
    policy: Optional[WarmupPolicy] = None,
) -> bool:
    policy = policy or WarmupPolicy()
    return n_observations >= max(policy.min_observations, n_features + 1)


__all__ = ["WarmupPolicy", "covariance_is_usable", "is_warming_up", "policy_from_env"]
