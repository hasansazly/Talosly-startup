"""Oracle response schema for Talosly ensemble scoring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict


Action = Literal["SAFE", "WARN", "ALERT", "PAUSE"]


class SignalPayload(TypedDict):
    """Individual model signals returned by the oracle API."""

    anomaly: float
    drain_velocity: float
    bayesian_deviation: float


@dataclass(frozen=True)
class OracleRiskResponse:
    """Full risk response produced by the hybrid ML + GPT scoring engine."""

    score: int
    confidence: float
    interval: list[int]
    p_exploit: float
    signals: SignalPayload
    gpt_consulted: bool
    gpt_reasoning: str | None
    action: Action
    warning: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable response payload."""
        payload: dict[str, object] = {
            "score": self.score,
            "confidence": self.confidence,
            "interval": self.interval,
            "p_exploit": self.p_exploit,
            "signals": self.signals,
            "gpt_consulted": self.gpt_consulted,
            "gpt_reasoning": self.gpt_reasoning,
            "action": self.action,
        }
        if self.warning:
            payload["warning"] = self.warning
        return payload


def action_for_score(score: int) -> Action:
    """Map a 0-100 risk score into Talosly's action ladder."""
    if score > 85:
        return "PAUSE"
    if score >= 65:
        return "ALERT"
    if score >= 40:
        return "WARN"
    return "SAFE"


def confidence_from_interval(interval: list[int]) -> float:
    """Convert a bootstrap interval width into a 0-1 confidence value."""
    if len(interval) != 2:
        return 0.0
    width = max(0, interval[1] - interval[0])
    return round(max(0.0, min(1.0, 1.0 - width / 100)), 4)
