"""Pre-filter rules for deciding whether a blockchain transaction needs scoring."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pybloom_live import BloomFilter

try:
    from web3 import Web3
except ImportError:
    class Web3:
        """Small fallback for address validation when web3.py is unavailable."""

        @staticmethod
        def is_address(value: str) -> bool:
            return isinstance(value, str) and value.startswith("0x") and len(value) == 42

        @staticmethod
        def to_checksum_address(value: str) -> str:
            if not Web3.is_address(value):
                raise ValueError(f"Invalid Ethereum address: {value!r}")
            return value.lower()


class _AddressBloomFilter:
    """Probabilistic Bloom Filter facade used by the pre-filter blacklist."""

    def __init__(self, capacity: int = 100_000, error_rate: float = 0.001) -> None:
        self._filter = BloomFilter(capacity=capacity, error_rate=error_rate)

    def add(self, value: str) -> None:
        self._filter.add(value)

    def __contains__(self, value: str) -> bool:
        return value in self._filter


class TransactionPreFilter:
    """Fast pre-filter that skips obviously safe transactions and escalates risky ones."""

    def __init__(self, blacklist_path: str | Path | None = None) -> None:
        self.blacklist_path = Path(blacklist_path) if blacklist_path else Path(__file__).with_name("blacklist.txt")
        self.blacklist = self._initialize_blacklist()
        self.safe_routers: set[str] = {
            "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45",
            "0xe592427a0aece92de3edee1f18e0157c05861564",
            "0x1111111254eeb25477b68fb85ed929f73a960582",
        }
        self.safe_selectors: set[str] = {
            "095ea7b3",
            "23b872dd",
            "38ed1739",
            "414bf389",
            "5ae401dc",
            "7ff36ab5",
            "ac9650d8",
        }
        self.sensitive_selectors: set[str] = {
            "5cffe9de",
            "ab9c4b5d",
            "3659cfe6",
            "4f1ef286",
            "f2fde38b",
            "79ba5097",
        }
        self.bloom_blacklist = self.blacklist

    def _initialize_blacklist(self) -> _AddressBloomFilter:
        """Load blacklisted addresses into the Bloom Filter."""
        blacklist = _AddressBloomFilter()
        seen: set[str] = set()

        if self.blacklist_path.exists():
            for line in self.blacklist_path.read_text().splitlines():
                addr = line.strip()
                if not addr or addr.startswith("#"):
                    continue
                if not Web3.is_address(addr):
                    logging.warning(f"Skipped invalid address: {addr!r}")
                    continue
                checksum_addr = Web3.to_checksum_address(addr)
                if checksum_addr in seen:
                    continue
                seen.add(checksum_addr)
                blacklist.add(checksum_addr)
            logging.info("Loaded %s blacklisted addresses", len(seen))
            return blacklist

        # Replace these fake placeholders with real threat intelligence feeds in production.
        for addr in (
            "0x000000000000000000000000000000000000DEAD",
            "0x000000000000000000000000000000000000BEEF",
        ):
            checksum_addr = Web3.to_checksum_address(addr)
            if checksum_addr in seen:
                continue
            seen.add(checksum_addr)
            blacklist.add(checksum_addr)
        logging.info("Loaded %s blacklisted addresses", len(seen))
        return blacklist

    def should_evaluate(self, tx: dict[str, Any]) -> tuple[bool, str]:
        """
        Evaluates incoming transaction data in microseconds.
        Returns (True, reason) -> Escalate to Layer 2 Feature Engineering.
        Returns (False, reason) -> Skip heavy scoring and save directly to DB.
        """
        to_address = tx.get("to_address") or tx.get("to")
        from_address = tx.get("from_address") or tx.get("from")
        input_data = str(tx.get("input_data") or tx.get("input") or "0x")
        value_wei = self._value_wei(tx)

        if not to_address:
            return True, "Contract creation transaction (High Risk)"
        if not from_address:
            return True, "Missing from_address validation escalation"

        to_checksum = Web3.to_checksum_address(to_address)
        from_checksum = Web3.to_checksum_address(from_address)
        selector = self._selector(input_data)

        if to_checksum in self.bloom_blacklist or from_checksum in self.bloom_blacklist:
            return True, "Blacklisted address match caught in Bloom Filter"

        if value_wei > 100 * 10**18:
            return True, "High-value asset movement detected"

        if to_checksum.lower() in self.safe_routers:
            if selector in self.safe_selectors:
                return False, "Routine transaction on verified safe protocol router"
            return False, "Safe router complex interaction (Fast Pass)"

        if selector not in self.safe_selectors:
            return True, f"Unverified function selector invocation: {selector}"

        return True, "Default structural check escalation"

    @staticmethod
    def _value_wei(tx: dict[str, Any]) -> int:
        """Return transaction value in wei from common RPC/enriched shapes."""
        if "value" not in tx and tx.get("value_eth") is not None:
            return int(float(tx["value_eth"]) * 10**18)
        value = tx.get("value", 0)
        if isinstance(value, str):
            try:
                return int(value, 0)
            except ValueError:
                return 0
        if isinstance(value, float):
            return int(value * 10**18)
        if value is None and tx.get("value_eth") is not None:
            return int(float(tx["value_eth"]) * 10**18)
        return int(value or 0)

    @staticmethod
    def _selector(input_data: str) -> str:
        """Extract the 4-byte function selector from transaction input data."""
        clean_input = input_data.lower()
        if clean_input.startswith("0x"):
            clean_input = clean_input[2:]
        return clean_input[:8] if len(clean_input) >= 8 else ""


class PreFilterManager(TransactionPreFilter):
    """Compatibility wrapper for the Layer 1 transaction pre-filter."""
