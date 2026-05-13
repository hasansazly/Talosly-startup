"""
Historical Backtesting Script for Talosly
=========================================
Replays known historical hacks through TransactionScorer to evaluate whether
current detection logic would have caught them.

SAFE TO RUN: Does not write to the production database or fire real Telegram
alerts. Side effects are suppressed via environment overrides and mock patching
before app code is imported.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# 1. SAFETY GUARDRAILS - Must happen BEFORE importing any app code.
# ---------------------------------------------------------------------------
os.environ.setdefault("BACKTEST_MODE", "1")
os.environ["OPENAI_API_KEY"] = ""
os.environ["ETHERSCAN_API_KEY"] = ""
os.environ["TELEGRAM_BOT_TOKEN"] = "DISABLED"
os.environ["TELEGRAM_CHAT_ID"] = "DISABLED"

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ---------------------------------------------------------------------------
# 2. PATCH DATABASE + TELEGRAM before importing scorer.
# ---------------------------------------------------------------------------
_patches = [
    patch("backend.database.get_pool", AsyncMock()),
    patch("backend.database.insert_alert", AsyncMock()),
    patch("backend.database.mark_telegram_sent", AsyncMock()),
    patch("backend.database.update_transaction_score", AsyncMock()),
    patch("backend.services.telegram.TelegramService.send_alert", AsyncMock(return_value=False)),
]
for p in _patches:
    try:
        p.start()
    except (AttributeError, ModuleNotFoundError):
        pass

# Compatibility patches for older layouts if this script is copied between repos.
for target in (
    "backend.db.session.add",
    "backend.db.session.commit",
    "backend.db.session.flush",
    "backend.services.alerts.send_telegram_alert",
    "backend.services.alerts.send_alert",
):
    try:
        patch(target, MagicMock()).start()
    except (AttributeError, ModuleNotFoundError):
        pass

# ---------------------------------------------------------------------------
# 3. Import the real scorer.
# ---------------------------------------------------------------------------
try:
    from backend.services.scorer import TransactionScorer
    from backend.services.blacklist import BLACKLIST
    from backend.services.scorer import norm
except ImportError as exc:
    print(f"\n[ERROR] Could not import TransactionScorer: {exc}")
    print("  Make sure you're running from the repo root, e.g.:")
    print("      python -m backend.tests.backtest_hacks\n")
    sys.exit(1)


@dataclass(frozen=True)
class BacktestCase:
    preset: str
    name: str
    description: str
    tx_data: dict[str, Any]
    protocol: dict[str, Any]
    pass_threshold: int = 80
    verify_behavior_without_blacklist: bool = False


HISTORICAL_HACKS: list[BacktestCase] = [
    BacktestCase(
        preset="venus",
        name="Venus Protocol - Donation Attack (March 2026)",
        description=(
            "Attacker donated tokens directly to the Venus vToken contract, "
            "artificially inflating the exchange rate and draining collateral. "
            "Simulated as a 0 ETH call from the attacker EOA with large calldata."
        ),
        protocol={
            "name": "Venus Protocol",
            "address": "0x737bc98f1d34e19539c074b8ad1169d5d45da619",
        },
        tx_data={
            "tx_hash": "0xVENUS_DONATION_ATTACK_SIMULATION_2026",
            "from_address": "0x1A35bD28EFD46CfC46c2136f878777D69ae16231",
            "to_address": "0x737bc98f1d34e19539c074b8ad1169d5d45da619",
            "value_eth": 0.0,
            "input_data": (
                "0xa9059cbb"
                "0000000000000000000000001a35bd28efd46cfc46c2136f878777d69ae16231"
                "00000000000000000000000000000000000000000000d3c21bcecceda1000000"
                + "00" * 128
            ),
        },
    ),
    BacktestCase(
        preset="euler",
        name="Euler Finance - Flash Loan Attack (March 2023)",
        description=(
            "Attacker used a flash loan from Aave to exploit a flaw in Euler's "
            "donateToReserves function, bypassing solvency checks and draining "
            "$197M in DAI, USDC, WETH, and stETH."
        ),
        protocol={
            "name": "Euler Finance",
            "address": "0x27182842E098f60e3D576794A5bFFb0777E025d3",
        },
        tx_data={
            "tx_hash": "0xEULER_FLASH_LOAN_ATTACK_SIMULATION_2023",
            "from_address": "0xb66cd966670d962c227b3eaba30a872dbfb995db",
            "to_address": "0x27182842E098f60e3D576794A5bFFb0777E025d3",
            "value_eth": 0,
            "input_data": "0x",
        },
        pass_threshold=80,
        verify_behavior_without_blacklist=True,
    ),
]

PRESETS: tuple[str, ...] = ("all", *(case.preset for case in HISTORICAL_HACKS))

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
WARN = "\033[93mWARN\033[0m"
RESET = "\033[0m"
BOLD = "\033[1m"


async def run_backtest(case: BacktestCase, scorer: TransactionScorer) -> bool:
    sep = "-" * 60
    print(f"\n{sep}")
    print(f"{BOLD}{case.name}{RESET}")
    print(f"    {case.description}")
    print(sep)

    matched = _blacklist_matches(case.tx_data)
    if matched:
        print("\n  Blacklist Match:")
        for field, address in matched:
            print(f"    - {field}: {address}")

    try:
        result = await scorer.score_transaction(case.tx_data, case.protocol)
    except Exception as exc:
        print(f"  [ERROR] scorer.score_transaction() raised: {exc}")
        return False

    if isinstance(result, dict):
        risk_score = result.get("risk_score", result.get("score", 0))
        risk_factors = result.get("risk_factors", result.get("factors", []))
    else:
        risk_score = getattr(result, "risk_score", getattr(result, "score", 0))
        risk_factors = getattr(result, "risk_factors", getattr(result, "factors", []))

    print(f"\n  {'Risk Score':15s}: {BOLD}{risk_score}{RESET}")
    print(f"  {'Threshold':15s}: {case.pass_threshold}")

    if risk_factors:
        print("\n  Risk Factors Identified:")
        for factor in risk_factors:
            print(f"    - {factor}")
    else:
        print(f"\n  {WARN} No risk factors returned by scorer.")

    caught = risk_score >= case.pass_threshold
    if caught:
        print(f"\n  {PASS} Score {risk_score} >= {case.pass_threshold} - hack would have been flagged.")
    else:
        print(f"\n  {FAIL} Score {risk_score} < {case.pass_threshold}")
        print(f"  {WARN} System would have missed this hack. Refine heuristics.")

    if case.verify_behavior_without_blacklist:
        await run_behavior_probe(case, scorer)

    return caught


def _blacklist_matches(tx_data: dict[str, Any]) -> list[tuple[str, str]]:
    matches = []
    for field in ("from_address", "from", "to_address", "to"):
        address = norm(tx_data.get(field))
        if address in BLACKLIST:
            matches.append((field, address))
    return matches


async def run_behavior_probe(case: BacktestCase, scorer: TransactionScorer) -> bool:
    matched_addresses = {address for _, address in _blacklist_matches(case.tx_data)}
    if not matched_addresses:
        return True

    print(f"\n  Behavior Probe: temporarily ignoring {len(matched_addresses)} blacklist address(es)")
    original = set(BLACKLIST)
    try:
        BLACKLIST.difference_update(matched_addresses)
        result = await scorer.score_transaction(case.tx_data, case.protocol)
    finally:
        BLACKLIST.clear()
        BLACKLIST.update(original)

    if isinstance(result, dict):
        risk_score = result.get("risk_score", result.get("score", 0))
        risk_factors = result.get("risk_factors", result.get("factors", []))
    else:
        risk_score = getattr(result, "risk_score", getattr(result, "score", 0))
        risk_factors = getattr(result, "risk_factors", getattr(result, "factors", []))

    if risk_score >= case.pass_threshold:
        print(f"  {PASS} Behavior-only score {risk_score} >= {case.pass_threshold}")
        return True

    print(f"  {WARN} Behavior-only score {risk_score} < {case.pass_threshold}")
    print(f"  {'Risk Factors':15s}: {risk_factors or 'none'}")
    return False


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Talosly historical hack backtester")
    parser.add_argument(
        "--preset",
        default="all",
        choices=PRESETS,
        help="Backtest preset to run.",
    )
    return parser.parse_args(argv)


def select_cases(preset: str) -> list[BacktestCase]:
    if preset == "all":
        return list(HISTORICAL_HACKS)
    return [case for case in HISTORICAL_HACKS if case.preset == preset]


async def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    cases = select_cases(args.preset)

    print(f"\n{'=' * 60}")
    print(f"{BOLD}Talosly - Historical Hack Backtester{RESET}")
    print("Running in SAFE mode: no DB writes, no Telegram alerts")
    print(f"Preset: {args.preset}")
    print(f"{'=' * 60}")

    scorer = TransactionScorer()
    results: list[tuple[str, bool]] = []
    for case in cases:
        results.append((case.name, await run_backtest(case, scorer)))

    total = len(results)
    caught = sum(1 for _, ok in results if ok)
    missed = total - caught

    print(f"\n{'=' * 60}")
    print(f"{BOLD}Summary: {caught}/{total} hacks caught{RESET}")
    print(f"{'=' * 60}")
    for name, ok in results:
        print(f"  {PASS if ok else FAIL} {name}")

    if missed:
        print(f"\n  {WARN} {missed} hack(s) were NOT caught - review scorer heuristics.\n")
        sys.exit(1)

    print("\n  All historical hacks detected.\n")
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
