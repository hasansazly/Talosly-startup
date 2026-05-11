"""
Talosly scoring evaluation suite.

Usage:
    python replay_suite.py
    python replay_suite.py --category TRUE_POSITIVE
    python replay_suite.py --category FALSE_POSITIVE_TEST
    python replay_suite.py --verbose
    python replay_suite.py --json > results.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("BACKTEST_MODE", "1")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "DISABLED")
os.environ.setdefault("TELEGRAM_CHAT_ID", "DISABLED")

from backend.services.blacklist import BLACKLIST  # noqa: E402
from backend.services.scorer import TransactionScorer  # noqa: E402


TEST_CASES_PATH = Path(__file__).parent / "replay_test_cases.json"


@dataclass
class TestResult:
    id: str
    description: str
    category: str
    expected_min: int
    expected_max: int
    expected_band: str
    actual_score: int
    actual_factors: list[str]
    actual_summary: str
    passed: bool
    blacklist_disabled: bool
    notes: str
    failure_reason: str = ""


@dataclass
class SuiteReport:
    total: int = 0
    passed: int = 0
    failed: int = 0
    true_positives_passed: int = 0
    true_positives_total: int = 0
    false_positive_tests_passed: int = 0
    false_positive_tests_total: int = 0
    results: list[TestResult] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return (self.passed / self.total * 100) if self.total else 0

    @property
    def true_positive_rate(self) -> float:
        return (self.true_positives_passed / self.true_positives_total * 100) if self.true_positives_total else 0

    @property
    def false_positive_rate(self) -> float:
        if not self.false_positive_tests_total:
            return 0
        failed_fp = self.false_positive_tests_total - self.false_positive_tests_passed
        return failed_fp / self.false_positive_tests_total * 100


async def neutral_address_label(_address: str) -> dict[str, Any]:
    return {
        "label": None,
        "is_dangerous": False,
        "is_new_wallet": False,
        "funded_by_tornado": False,
        "tx_count": -1,
    }


async def run_test_case(scorer: TransactionScorer, case: dict[str, Any]) -> TestResult:
    original_blacklist = set(BLACKLIST)
    if case.get("blacklist_disabled"):
        BLACKLIST.clear()

    try:
        transaction = {
            "tx_hash": case["tx_hash"],
            "from_address": case["from_address"],
            "to_address": case["to_address"],
            "value_eth": case["value_eth"],
            "gas_used": case["gas_used"],
            "input_data": case["input_data"],
        }
        result = scorer.pre_screen(transaction)
        if result is None:
            result = await scorer.score_transaction(transaction, {"name": "Replay Suite", "address": case["to_address"]})

        actual_score = int(result.risk_score)
        expected_min = int(case["expected_score_min"])
        expected_max = int(case["expected_score_max"])
        passed = expected_min <= actual_score <= expected_max
        failure_reason = ""
        if not passed:
            if actual_score < expected_min:
                failure_reason = f"Score too low: {actual_score} < {expected_min}"
            else:
                failure_reason = f"Score too high: {actual_score} > {expected_max}"

        return TestResult(
            id=case["id"],
            description=case["description"],
            category=case["category"],
            expected_min=expected_min,
            expected_max=expected_max,
            expected_band=case["expected_band"],
            actual_score=actual_score,
            actual_factors=list(result.risk_factors),
            actual_summary=result.risk_summary,
            passed=passed,
            blacklist_disabled=case.get("blacklist_disabled", False),
            notes=case.get("notes", ""),
            failure_reason=failure_reason,
        )
    finally:
        BLACKLIST.clear()
        BLACKLIST.update(original_blacklist)


def score_band(score: int) -> str:
    if score >= 85:
        return "CRITICAL"
    if score >= 70:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    if score >= 10:
        return "LOW"
    return "NORMAL"


def print_result(result: TestResult, verbose: bool = False) -> None:
    status = "PASS" if result.passed else "FAIL"
    print(f"\n{status} [{result.category}] {result.id}")
    print(f"  {result.description}")
    print(f"  Score: {result.actual_score} {score_band(result.actual_score)} (expected {result.expected_min}-{result.expected_max})")
    if result.blacklist_disabled:
        print("  Blacklist disabled: behavior-only test")
    if verbose or not result.passed:
        print(f"  Factors: {result.actual_factors}")
        print(f"  Summary: {result.actual_summary}")
        print(f"  Notes: {result.notes}")
    if result.failure_reason:
        print(f"  Reason: {result.failure_reason}")


def print_report(report: SuiteReport, verbose: bool = False) -> None:
    print("\n" + "=" * 60)
    print("TALOSLY SCORING EVALUATION REPORT")
    print("=" * 60)
    for result in report.results:
        print_result(result, verbose)
    print("\n" + "-" * 60)
    print(f"OVERALL:        {report.passed}/{report.total} passed ({report.accuracy:.1f}%)")
    print(f"TRUE POSITIVE:  {report.true_positives_passed}/{report.true_positives_total} ({report.true_positive_rate:.1f}%)")
    print(f"FALSE POSITIVE: {report.false_positive_tests_total - report.false_positive_tests_passed}/{report.false_positive_tests_total} ({report.false_positive_rate:.1f}%)")
    print("-" * 60)
    if report.failed:
        print("FAILED CASES:")
        for result in report.results:
            if not result.passed:
                print(f"  - {result.id}: {result.failure_reason}")
    else:
        print("All test cases passed.")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Talosly scoring evaluation suite")
    parser.add_argument("--category", help="Filter by category")
    parser.add_argument("--verbose", action="store_true", help="Show full details")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--cases", default=str(TEST_CASES_PATH), help="Path to test cases JSON")
    args = parser.parse_args()

    cases_path = Path(args.cases)
    if not cases_path.exists():
        print(f"Test cases not found: {cases_path}")
        sys.exit(1)

    cases = json.loads(cases_path.read_text())
    if args.category:
        cases = [case for case in cases if case["category"] == args.category]

    scorer = TransactionScorer()
    scorer.client = None
    scorer._get_wallet_reputation = neutral_wallet_reputation  # type: ignore[method-assign]

    import backend.services.scorer as scorer_module

    scorer_module.get_address_label = neutral_address_label

    report = SuiteReport(total=len(cases))
    for case in cases:
        result = await run_test_case(scorer, case)
        report.results.append(result)
        if result.passed:
            report.passed += 1
        else:
            report.failed += 1

        if "TRUE_POSITIVE" in result.category:
            report.true_positives_total += 1
            if result.passed:
                report.true_positives_passed += 1
        elif "FALSE_POSITIVE" in result.category:
            report.false_positive_tests_total += 1
            if result.passed:
                report.false_positive_tests_passed += 1

    if args.json:
        print(json.dumps({"summary": asdict(report) | {"accuracy": report.accuracy}, "results": [asdict(r) for r in report.results]}, indent=2))
    else:
        print_report(report, args.verbose)

    sys.exit(0 if report.failed == 0 else 1)


async def neutral_wallet_reputation(_address: str) -> dict[str, bool]:
    return {"is_new": False, "has_no_ens": False}


if __name__ == "__main__":
    asyncio.run(main())
