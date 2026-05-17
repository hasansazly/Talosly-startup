"""GPT usage and cost tracking for Talosly ensemble scoring."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


INPUT_COST_PER_1K = 0.00015
OUTPUT_COST_PER_1K = 0.00060
DEFAULT_LOG_PATH = Path("gpt_usage.log")


@dataclass(frozen=True)
class CostReport:
    """Aggregated GPT cost report."""

    today_usd: float
    month_usd: float
    calls_saved_by_ml: int
    estimated_savings_usd: float

    def to_dict(self) -> dict[str, float | int]:
        """Return a JSON-serializable cost report."""
        return {
            "today_usd": self.today_usd,
            "month_usd": self.month_usd,
            "calls_saved_by_ml": self.calls_saved_by_ml,
            "estimated_savings_usd": self.estimated_savings_usd,
        }


class CostTracker:
    """Append-only tracker for GPT calls and ML-gated savings."""

    def __init__(self, log_path: Path | str = DEFAULT_LOG_PATH) -> None:
        self.log_path = Path(log_path)

    def log_gpt_call(
        self,
        *,
        protocol: str,
        input_tokens: int,
        output_tokens: int,
        score_delta: int,
    ) -> None:
        """Record one GPT call with token usage and final score impact."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "protocol": protocol,
            "input_tokens": max(0, int(input_tokens)),
            "output_tokens": max(0, int(output_tokens)),
            "cost_usd": estimate_cost_usd(input_tokens, output_tokens),
            "score_delta": int(score_delta),
            "call_saved": False,
        }
        self._append(entry)

    def log_saved_call(self, *, protocol: str, estimated_tokens: int = 500) -> None:
        """Record one GPT call avoided by the ML gate."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "protocol": protocol,
            "input_tokens": max(0, int(estimated_tokens)),
            "output_tokens": 0,
            "cost_usd": estimate_cost_usd(estimated_tokens, 0),
            "score_delta": 0,
            "call_saved": True,
        }
        self._append(entry)

    def report(self, protocol: str | None = None) -> CostReport:
        """Aggregate daily and monthly GPT costs from the usage log."""
        now = datetime.now(timezone.utc)
        today = now.date()
        month = (now.year, now.month)
        today_usd = 0.0
        month_usd = 0.0
        calls_saved = 0
        estimated_savings = 0.0

        for entry in self._entries():
            if protocol and entry.get("protocol") != protocol:
                continue
            timestamp = _parse_timestamp(str(entry.get("timestamp", "")))
            if timestamp is None:
                continue
            cost = float(entry.get("cost_usd") or 0)
            if bool(entry.get("call_saved")):
                calls_saved += 1
                estimated_savings += cost
                continue
            if timestamp.date() == today:
                today_usd += cost
            if (timestamp.year, timestamp.month) == month:
                month_usd += cost

        return CostReport(
            today_usd=round(today_usd, 6),
            month_usd=round(month_usd, 6),
            calls_saved_by_ml=calls_saved,
            estimated_savings_usd=round(estimated_savings, 6),
        )

    async def alert_if_needed(
        self,
        *,
        threshold_usd: float,
        notifier: Callable[[str], Any] | None = None,
    ) -> bool:
        """Notify when today's GPT spend exceeds the configured threshold."""
        report = self.report()
        if report.today_usd <= threshold_usd or notifier is None:
            return False
        result = notifier(f"Talosly GPT spend alert: ${report.today_usd:.2f} today")
        if hasattr(result, "__await__"):
            await result
        return True

    def _append(self, entry: dict[str, object]) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")

    def _entries(self) -> list[dict[str, object]]:
        if not self.log_path.exists():
            return []
        entries: list[dict[str, object]] = []
        with self.log_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries


def estimate_cost_usd(input_tokens: int, output_tokens: int) -> float:
    """Estimate GPT-4o mini cost for token counts."""
    input_cost = max(0, input_tokens) / 1000 * INPUT_COST_PER_1K
    output_cost = max(0, output_tokens) / 1000 * OUTPUT_COST_PER_1K
    return round(input_cost + output_cost, 8)


def _parse_timestamp(value: str) -> datetime | None:
    """Parse an ISO timestamp, returning None for malformed log lines."""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
