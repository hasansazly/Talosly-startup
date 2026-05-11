"""
Replay a historical Ethereum transaction through Talosly's scorer.

Usage:
    python replay_hack.py <tx_hash>
    python replay_hack.py <tx_hash> --protocol-name "Balancer V2" --protocol-address 0x...

Safety:
    This script does not write to the database and does not send Telegram alerts.
    It imports the existing RPC client and TransactionScorer only.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv

# Guardrails: set before importing app services.
load_dotenv()
os.environ.setdefault("BACKTEST_MODE", "1")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "DISABLED")
os.environ.setdefault("TELEGRAM_CHAT_ID", "DISABLED")

from backend.services.rpc import EthereumRPCClient  # noqa: E402
from backend.services.blacklist import BLACKLIST  # noqa: E402
from backend.services.scorer import TransactionScorer  # noqa: E402


RISK_THRESHOLD = 70


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    path_parts = [part for part in parts.path.split("/") if part]
    if path_parts:
        path_parts[-1] = "***"
    redacted_path = "/" + "/".join(path_parts) if path_parts else parts.path
    return urlunsplit((parts.scheme, parts.netloc, redacted_path, parts.query, parts.fragment))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay a historical Ethereum transaction through Talosly's TransactionScorer.",
    )
    parser.add_argument("tx_hash", help="Ethereum transaction hash to replay.")
    parser.add_argument(
        "--protocol-name",
        default="Historical Replay Target",
        help="Protocol name to pass into the scorer.",
    )
    parser.add_argument(
        "--protocol-address",
        default=None,
        help="Protocol address to pass into the scorer. Defaults to the transaction recipient.",
    )
    parser.add_argument(
        "--ignore-blacklist",
        action="store_true",
        help="Temporarily disable blacklist matches for this replay run.",
    )
    return parser.parse_args()


async def fetch_transaction(rpc: EthereumRPCClient, tx_hash: str) -> dict[str, Any]:
    raw_tx = await rpc._call("eth_getTransactionByHash", [tx_hash])
    print(f"DEBUG: RPC Response: {raw_tx}")
    if not raw_tx:
        receipt = await rpc.get_transaction_receipt(tx_hash)
        print(f"DEBUG: Receipt Response: {receipt}")
        raise ValueError(
            "Transaction not found by the configured Ethereum RPC provider.\n"
            f"  tx_hash: {tx_hash}\n"
            f"  rpc_url: {redact_url(rpc.rpc_url)}\n"
            "Check that the hash is a real Ethereum mainnet transaction and that "
            "ETHEREUM_RPC_URL points to an archive-capable/mainnet provider."
        )

    receipt = await rpc.get_transaction_receipt(tx_hash)
    tx = rpc.parse_transaction(raw_tx, receipt)
    if not tx.get("gas_used") and raw_tx.get("gas"):
        tx["gas_used"] = int(raw_tx["gas"], 16) if isinstance(raw_tx["gas"], str) else raw_tx["gas"]
    print(f"DEBUG: Parsed Transaction: {tx}")
    return tx


def build_protocol(args: argparse.Namespace, tx: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": args.protocol_name,
        "address": args.protocol_address or tx.get("to_address") or "unknown",
    }


def print_report(tx: dict[str, Any], protocol: dict[str, Any], result: Any) -> None:
    risk_score = int(getattr(result, "risk_score", 0))
    risk_summary = getattr(result, "risk_summary", "No summary returned")
    risk_factors = getattr(result, "risk_factors", []) or []
    caught = risk_score > RISK_THRESHOLD

    print("\nSecurity Report")
    print("=" * 60)
    print(f"Protocol:     {protocol.get('name')}")
    print(f"Protocol Addr:{protocol.get('address')}")
    print(f"TX Hash:      {tx.get('tx_hash')}")
    print(f"From:         {tx.get('from_address')}")
    print(f"To:           {tx.get('to_address')}")
    print(f"Value ETH:    {tx.get('value_eth')}")
    print(f"Block:        {tx.get('block_number')}")
    print("-" * 60)
    print(f"Risk Score:   {risk_score}")
    print(f"Summary:      {risk_summary}")
    print(f"Risk Factors: {', '.join(risk_factors) if risk_factors else 'None'}")
    print(f"Caught:       {'YES' if caught else 'NO'}")
    print("=" * 60)


async def main() -> None:
    args = parse_args()
    if args.ignore_blacklist:
        BLACKLIST.clear()
        print("DEBUG: Blacklist disabled for this replay run.")

    rpc = EthereumRPCClient()
    scorer = TransactionScorer()

    tx = await fetch_transaction(rpc, args.tx_hash)
    protocol = build_protocol(args, tx)
    result = await scorer.score_transaction(tx, protocol)

    print_report(tx, protocol, result)


if __name__ == "__main__":
    asyncio.run(main())
