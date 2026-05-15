"""
Live RPC replay accuracy suite for Talosly.

This validates real Ethereum transactions through the same RPC parser and
TransactionScorer path used by /api/demo/replay. It does not write to the
database or send alerts.

Usage:
    python3 replay_live_suite.py
    python3 replay_live_suite.py --cases replay_live_cases.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("BACKTEST_MODE", "1")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "DISABLED")
os.environ.setdefault("TELEGRAM_CHAT_ID", "DISABLED")

from backend.services.rpc import EthereumRPCClient  # noqa: E402
from backend.services.scorer import TransactionScorer  # noqa: E402
import backend.services.scorer as scorer_module  # noqa: E402


DEFAULT_CASES = Path(__file__).parent / "replay_live_cases.json"


@dataclass
class LiveReplayResult:
    id: str
    description: str
    score: int
    expected_min: int
    expected_max: int
    factors: list[str]
    summary: str
    passed: bool
    failure_reason: str = ""


async def fetch_transaction(rpc: EthereumRPCClient, tx_hash: str) -> dict[str, Any]:
    raw_tx = await rpc._call("eth_getTransactionByHash", [tx_hash])
    if not raw_tx:
      raise ValueError(f"Transaction not found on configured RPC: {tx_hash}")

    receipt = await rpc.get_transaction_receipt(tx_hash)
    tx = rpc.parse_transaction(raw_tx, receipt)
    tx["input_data"] = raw_tx.get("input") or tx.get("input_data") or ""
    return tx


async def run_case(rpc: EthereumRPCClient, scorer: TransactionScorer, case: dict[str, Any]) -> LiveReplayResult:
    tx = await fetch_transaction(rpc, case["tx_hash"])
    protocol = {
        "name": case.get("protocol_name", "Live Replay Target"),
        "address": case.get("protocol_address") or tx.get("to_address") or "unknown",
    }
    result = await scorer.score_transaction(tx, protocol)
    score = int(result.risk_score)
    factors = list(result.risk_factors)
    expected_min = int(case["expected_score_min"])
    expected_max = int(case["expected_score_max"])

    failures = []
    if not expected_min <= score <= expected_max:
        failures.append(f"score {score} outside {expected_min}-{expected_max}")

    expected_any = set(case.get("expected_factors_any") or [])
    if expected_any and not (expected_any & set(factors)):
        failures.append(f"missing expected factor; wanted one of {sorted(expected_any)}, got {factors}")

    return LiveReplayResult(
        id=case["id"],
        description=case["description"],
        score=score,
        expected_min=expected_min,
        expected_max=expected_max,
        factors=factors,
        summary=result.risk_summary,
        passed=not failures,
        failure_reason="; ".join(failures),
    )


async def neutral_address_label(_address: str) -> dict[str, Any]:
    return {
        "label": None,
        "is_dangerous": False,
        "is_new_wallet": False,
        "funded_by_tornado": False,
        "tx_count": -1,
    }


async def neutral_wallet_reputation(_address: str) -> dict[str, bool]:
    return {"is_new": False, "has_no_ens": False}


def print_result(result: LiveReplayResult) -> None:
    status = "PASS" if result.passed else "FAIL"
    print(f"\n{status} {result.id}")
    print(f"  {result.description}")
    print(f"  Score: {result.score} (expected {result.expected_min}-{result.expected_max})")
    print(f"  Factors: {result.factors}")
    print(f"  Summary: {result.summary}")
    if result.failure_reason:
        print(f"  Reason: {result.failure_reason}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run live Talosly replay accuracy checks.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES), help="Path to live replay cases JSON.")
    args = parser.parse_args()

    cases = json.loads(Path(args.cases).read_text())
    rpc = EthereumRPCClient()
    scorer = TransactionScorer()
    scorer._get_wallet_reputation = neutral_wallet_reputation  # type: ignore[method-assign]
    scorer_module.get_address_label = neutral_address_label
    results = [await run_case(rpc, scorer, case) for case in cases]

    print("\nTALOSLY LIVE REPLAY ACCURACY")
    print("=" * 60)
    for result in results:
        print_result(result)

    passed = sum(1 for result in results if result.passed)
    print("\n" + "-" * 60)
    print(f"OVERALL: {passed}/{len(results)} passed")
    print("-" * 60)
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
