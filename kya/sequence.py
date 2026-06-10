"""Markov n-gram model for agent action trajectory scoring.

Each agent action is encoded as a (selector, counterparty-class, value-bucket) state.
Transitions between states are counted and used to score how surprising the current
action is under the agent's own history. Near-zero probability transitions are a strong
injection signal — injected agents produce action sequences inconsistent with their
established behavioral fingerprint.
"""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

MIN_TRANSITIONS = 5
LAPLACE_ALPHA = 1.0
MAX_TRANSITION_ENTRIES = 2_000


def state_from_event(
    selector: str | None,
    counterparty: str | None,
    value: float,
    known_counterparties: set[str],
) -> str:
    """Encode one agent action as a Markov state key."""
    sel = (selector or "none")[:8].lower()
    cp_class = "known" if (counterparty or "").lower() in known_counterparties else "unseen"
    vb = _value_bucket(value)
    return f"{sel}|{cp_class}|{vb}"


def score_transition(
    seq: dict[str, Any],
    prev_state: str,
    curr_state: str,
) -> float:
    """Return anomaly score [0, 1] for this transition under the agent's Markov history.

    0 = expected (high-probability) transition.
    1 = completely unexpected (near-zero probability under this agent's history).
    Returns 0.0 if there is insufficient history to score.
    """
    transitions = seq.get("transitions") or {}
    transition_count = int(seq.get("transition_count") or 0)
    if transition_count < MIN_TRANSITIONS or not prev_state:
        return 0.0

    from_counts = transitions.get(prev_state)
    if not from_counts:
        # prev_state never seen as a source — novel trajectory break.
        return 0.5

    all_to: set[str] = set()
    for to_dict in transitions.values():
        all_to.update(to_dict.keys())
    vocab = max(len(all_to), 1)

    total_from = sum(from_counts.values())
    count = int(from_counts.get(curr_state, 0))
    prob = (count + LAPLACE_ALPHA) / (total_from + LAPLACE_ALPHA * vocab)
    nlp = -math.log(prob)

    # Primary path: z-score once we have enough log-prob observations.
    log_stats = seq.get("log_prob_stats") or {}
    z = _zscore(nlp, log_stats)
    if z is not None:
        return float(min(max(z / 6.0, 0.0), 1.0))

    # Fallback: normalize between the most-probable and least-probable NLP
    # achievable from this source state — adapts to any vocabulary size.
    nlp_min = -math.log((total_from + LAPLACE_ALPHA) / (total_from + LAPLACE_ALPHA * vocab))
    nlp_max = -math.log(LAPLACE_ALPHA / (total_from + LAPLACE_ALPHA * vocab))
    if nlp_max <= nlp_min:
        return 0.0
    return float(min(max((nlp - nlp_min) / (nlp_max - nlp_min), 0.0), 1.0))


def compute_neg_log_prob(
    seq: dict[str, Any],
    prev_state: str,
    curr_state: str,
) -> float | None:
    """Negative log-probability of curr_state given prev_state, or None if not scoreable."""
    transitions = seq.get("transitions") or {}
    if int(seq.get("transition_count") or 0) < MIN_TRANSITIONS or not prev_state:
        return None
    from_counts = transitions.get(prev_state)
    if not from_counts:
        return None
    return _neg_log_prob(transitions, prev_state, curr_state)


def update_sequence(
    seq: dict[str, Any],
    prev_state: str | None,
    curr_state: str,
    neg_log_prob: float | None = None,
) -> dict[str, Any]:
    """Record transition prev_state → curr_state and advance the cursor."""
    updated = deepcopy(seq)
    transitions = deepcopy(dict(updated.get("transitions") or {}))

    if prev_state:
        from_counts = dict(transitions.get(prev_state) or {})
        from_counts[curr_state] = int(from_counts.get(curr_state, 0)) + 1
        transitions[prev_state] = from_counts
        updated["transition_count"] = int(updated.get("transition_count") or 0) + 1

        if neg_log_prob is not None:
            updated["log_prob_stats"] = _update_running_stats(
                dict(updated.get("log_prob_stats") or {}), neg_log_prob
            )

        if sum(len(v) for v in transitions.values()) > MAX_TRANSITION_ENTRIES:
            transitions = _prune(transitions)

    updated["transitions"] = transitions
    updated["prev_state"] = curr_state
    return updated


def _neg_log_prob(transitions: dict, prev_state: str, curr_state: str) -> float | None:
    from_counts = transitions.get(prev_state) or {}
    total_from = sum(from_counts.values())
    if total_from == 0:
        return None

    all_to: set[str] = set()
    for to_dict in transitions.values():
        all_to.update(to_dict.keys())
    vocab = max(len(all_to), 1)

    count = int(from_counts.get(curr_state, 0))
    prob = (count + LAPLACE_ALPHA) / (total_from + LAPLACE_ALPHA * vocab)
    return -math.log(prob)


def _value_bucket(value: float) -> str:
    if value < 0.001:
        return "dust"
    if value < 0.01:
        return "micro"
    if value < 0.1:
        return "small"
    if value < 1.0:
        return "medium"
    if value < 10.0:
        return "large"
    return "whale"


def _zscore(value: float, stats: dict[str, Any]) -> float | None:
    count = int(stats.get("count") or 0)
    std = float(stats.get("std") or 0.0)
    if count < 5 or std <= 0:
        return None
    return abs(value - float(stats.get("mean") or 0.0)) / std


def _update_running_stats(stats: dict[str, Any], value: float) -> dict[str, Any]:
    count = int(stats.get("count") or 0) + 1
    prev_mean = float(stats.get("mean") or 0.0)
    prev_m2 = float(stats.get("m2") or 0.0)
    delta = value - prev_mean
    mean = prev_mean + delta / count
    m2 = prev_m2 + delta * (value - mean)
    variance = m2 / (count - 1) if count > 1 else 0.0
    return {
        "count": count,
        "mean": round(mean, 6),
        "m2": round(m2, 6),
        "std": round(math.sqrt(max(variance, 0.0)), 6),
    }


def _prune(transitions: dict) -> dict:
    pruned = {
        from_state: {to: cnt for to, cnt in to_dict.items() if cnt > 1}
        for from_state, to_dict in transitions.items()
    }
    pruned = {k: v for k, v in pruned.items() if v}
    return pruned or transitions


__all__ = [
    "compute_neg_log_prob",
    "score_transition",
    "state_from_event",
    "update_sequence",
]
