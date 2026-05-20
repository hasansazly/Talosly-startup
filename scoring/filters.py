"""Pre-filter rules for deciding whether a blockchain transaction needs scoring."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

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
    """Set-backed Bloom Filter facade used by the pre-filter blacklist."""

    def __init__(self) -> None:
        self._items: set[str] = set()

    def add(self, value: str) -> None:
        self._items.add(value)

    def __contains__(self, value: str) -> bool:
        return value in self._items


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
        """Return whether a transaction should be evaluated by the scoring engine."""
        from_address = tx.get("from_address") or tx.get("from")
        if not from_address:
            return True, "Missing from_address (possible coinbase tx)"

        from_checksum = Web3.to_checksum_address(from_address)
        if from_checksum in self.blacklist:
            return True, "Sender address is blacklisted"

        to_address = tx.get("to_address") or tx.get("to")
        to_checksum = Web3.to_checksum_address(to_address) if to_address else ""
        input_data = str(tx.get("input_data") or tx.get("input") or "")
        selector = self._selector(input_data)
        is_safe_router = bool(to_checksum) and to_checksum.lower() in self.safe_routers
        is_safe_selector = selector in self.safe_selectors

        if is_safe_router:
            if is_safe_selector:
                return False, "Routine interaction on verified safe router"
            return False, "Safe router complex interaction (Fast Pass)"

        if selector not in self.safe_selectors:
            return True, f"Unverified function selector execution: {selector}"

        if selector in self.sensitive_selectors:
            return True, "Sensitive selector requires evaluation"

        if not to_checksum:
            return True, "Missing to_address"

        return True, "Default structural check escalation"

    @staticmethod
    def _selector(input_data: str) -> str:
        """Extract the 4-byte function selector from transaction input data."""
        clean_input = input_data.lower()
        if clean_input.startswith("0x"):
            clean_input = clean_input[2:]
        return clean_input[:8] if len(clean_input) >= 8 else ""


class PreFilterManager(TransactionPreFilter):
    """Compatibility wrapper for the Layer 1 transaction pre-filter."""
