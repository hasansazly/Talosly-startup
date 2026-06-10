"""Bayesian Online Change-Point Detection (BOCPD) for agent behavioral sequences.

Implements Adams & MacKay (2007).  At each action we maintain a posterior
over "run lengths" — how many consecutive steps the current behavioral regime
has lasted.  The change-point probability P(r_t = 0 | x_{1:t}) is a proper
Bayesian posterior, directly usable as evidence language:

  "P(behavioral regime change) = 0.97 at action #143"

The predictive model is a Normal-Inverse-Gamma (NIG) conjugate over
log-ETH-value.  This gives a Student-t predictive distribution that is
robust to outliers and requires no offline training: the model learns each
agent's personal value distribution on-line and flags departures from it.
"""

from __future__ import annotations

import math
from typing import Any

# Geometric prior on run lengths.  HAZARD_RATE = 0.02 → expected regime
# duration ≈ 50 actions, with P(run > 150) ≈ 5%.
HAZARD_RATE: float = 0.02
MAX_RUN: int = 150

# NIG prior hyperparameters for log-ETH-value.
# beta0 = 10 → prior predictive std ≈ 4.5 in log space, spanning 9 orders of
# magnitude of ETH value without asserting a preferred scale.
NIG_MU0: float = 0.0
NIG_KAPPA0: float = 1.0
NIG_ALPHA0: float = 1.0
NIG_BETA0: float = 10.0

_PRIOR: list[float] = [NIG_MU0, NIG_KAPPA0, NIG_ALPHA0, NIG_BETA0]


def empty_bocpd_state() -> dict[str, Any]:
    return {
        "hazard_rate": HAZARD_RATE,
        "run_probs": [1.0],
        "nig_runs": [list(_PRIOR)],
        "cp_prob": 0.0,
        "event_count": 0,
    }


def bocpd_score(state: dict[str, Any] | None, x: float) -> float:
    """Return P(change point at this observation) without advancing the state."""
    _, cp_prob = _step(state or empty_bocpd_state(), x)
    return cp_prob


def bocpd_update(state: dict[str, Any] | None, x: float) -> dict[str, Any]:
    """Incorporate observation x and return the updated BOCPD state."""
    s = state or empty_bocpd_state()
    new_state, cp_prob = _step(s, x)
    new_state["cp_prob"] = round(cp_prob, 6)
    new_state["event_count"] = int(s.get("event_count") or 0) + 1
    return new_state


def _step(state: dict[str, Any], x: float) -> tuple[dict[str, Any], float]:
    run_probs: list[float] = list(state.get("run_probs") or [1.0])
    nig_runs: list[list[float]] = [list(r) for r in (state.get("nig_runs") or [_PRIOR])]
    hazard: float = float(state.get("hazard_rate") or HAZARD_RATE)
    n = len(run_probs)

    log_h = math.log(hazard)
    log_1mh = math.log(1.0 - hazard)

    # Predictive log-probabilities.
    # r_{t+1} = 0 (change point): new regime, uses prior.
    # r_{t+1} = k+1 (growth from k): uses NIG posterior after k observations.
    log_pred_cp = _nig_log_pred(_PRIOR, x)
    log_pred_growth = [_nig_log_pred(nig_runs[k], x) for k in range(n)]

    # Log-joint P(r_{t+1}, x_{t+1}).
    # Change point: H × P(x | prior) × Σ run_probs[k] = H × P(x | prior)
    log_joint_cp = log_h + log_pred_cp
    log_joint_growth = [
        log_1mh + math.log(max(run_probs[k], 1e-300)) + log_pred_growth[k]
        for k in range(n)
    ]

    # Log-sum-exp normalization → posterior over run lengths.
    all_lj = [log_joint_cp] + log_joint_growth
    max_lj = max(all_lj)
    joints = [math.exp(lj - max_lj) for lj in all_lj]
    Z = sum(joints)
    new_run_probs = [j / Z for j in joints]

    cp_prob = float(new_run_probs[0])

    # Advance NIG posteriors: new run length k+1 incorporates x into run k's posterior.
    new_nig_runs = [list(_PRIOR)] + [_nig_update(nig_runs[k], x) for k in range(n)]

    # Truncate and renormalize (handles MAX_RUN boundary).
    if len(new_run_probs) > MAX_RUN:
        new_run_probs = new_run_probs[:MAX_RUN]
        new_nig_runs = new_nig_runs[:MAX_RUN]
        total = sum(new_run_probs)
        if total > 0:
            new_run_probs = [p / total for p in new_run_probs]

    new_state: dict[str, Any] = {
        "hazard_rate": hazard,
        "run_probs": [round(p, 8) for p in new_run_probs],
        "nig_runs": [[round(v, 6) for v in nig] for nig in new_nig_runs],
        "cp_prob": 0.0,
        "event_count": 0,
    }
    return new_state, cp_prob


def _nig_log_pred(nig: list[float], x: float) -> float:
    """Log-predictive P(x | NIG) = log Student-t PDF."""
    mu, kappa, alpha, beta = nig
    df = 2.0 * alpha
    loc = mu
    scale = math.sqrt(max(beta * (kappa + 1.0) / (alpha * kappa), 1e-12))
    return _student_t_log_pdf(x, df, loc, scale)


def _nig_update(nig: list[float], x: float) -> list[float]:
    """Conjugate NIG posterior update after observing x."""
    mu, kappa, alpha, beta = nig
    kappa_new = kappa + 1.0
    mu_new = (kappa * mu + x) / kappa_new
    alpha_new = alpha + 0.5
    beta_new = beta + (kappa * (x - mu) ** 2) / (2.0 * kappa_new)
    return [mu_new, kappa_new, alpha_new, beta_new]


def _student_t_log_pdf(x: float, df: float, loc: float, scale: float) -> float:
    """Log PDF of Student-t(df, loc, scale)."""
    z = (x - loc) / scale
    return (
        math.lgamma((df + 1.0) / 2.0)
        - math.lgamma(df / 2.0)
        - 0.5 * math.log(df * math.pi)
        - math.log(scale)
        - ((df + 1.0) / 2.0) * math.log(1.0 + z * z / df)
    )


__all__ = ["bocpd_score", "bocpd_update", "empty_bocpd_state"]
