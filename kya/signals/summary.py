"""First-class signal surfacing for score responses and receipts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

CHANGEPOINT = "changepoint"
MAHALANOBIS = "mahalanobis"
CONFORMAL = "conformal"

_PRIORITY = {CHANGEPOINT: 0, MAHALANOBIS: 1, CONFORMAL: 2}


@dataclass
class SignalResult:
    name: str
    enabled: bool
    fired: bool
    statistic: Optional[float] = None
    threshold: Optional[float] = None
    warming_up: bool = False
    extra: dict = field(default_factory=dict)

    def to_detail(self) -> dict:
        d = {"enabled": self.enabled, "fired": self.fired}
        if self.warming_up:
            d["warming_up"] = True
        if self.statistic is not None:
            d["statistic"] = self.statistic
        if self.threshold is not None:
            d["threshold"] = self.threshold
        if self.extra:
            d.update(self.extra)
        return d


@dataclass
class SignalSummary:
    signals_fired: list
    detail: dict
    changepoint: dict

    def to_dict(self) -> dict:
        return {
            "signals_fired": self.signals_fired,
            "signals_detail": self.detail,
            "changepoint": self.changepoint,
        }


def summarize(results: list[SignalResult]) -> SignalSummary:
    ordered = sorted(results, key=lambda r: (_PRIORITY.get(r.name, 99), r.name))
    fired = [r.name for r in ordered if r.enabled and r.fired]
    detail = {r.name: r.to_detail() for r in ordered}

    cp = next((r for r in ordered if r.name == CHANGEPOINT), None)
    changepoint = cp.to_detail() if cp is not None else {"enabled": False, "fired": False}

    return SignalSummary(signals_fired=fired, detail=detail, changepoint=changepoint)


__all__ = [
    "CHANGEPOINT",
    "CONFORMAL",
    "MAHALANOBIS",
    "SignalResult",
    "SignalSummary",
    "summarize",
]
