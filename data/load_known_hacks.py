"""Load and manage known exploit transaction hashes.

The backing file is newline-delimited JSON, but the loader also accepts plain
hash lines so small ad-hoc lists can be reused directly.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_PATH = Path(__file__).with_name("known_hacks.jsonl")
TX_HASH_RE = re.compile(r"^0x[a-fA-F0-9]{64}$")


@dataclass(frozen=True)
class HackRecord:
    hash: str
    protocol: str = "unknown"
    date: str = "unknown"
    chain: str = "ethereum"
    amount_usd: int = 0
    attack_type: str = "unknown"
    attacker: str = "unknown"
    source: str = "manual"

    @classmethod
    def from_obj(cls, obj: dict[str, Any]) -> "HackRecord | None":
        tx_hash = str(obj.get("hash") or obj.get("tx_hash") or "").lower()
        if not TX_HASH_RE.fullmatch(tx_hash):
            return None
        return cls(
            hash=tx_hash,
            protocol=str(obj.get("protocol") or "unknown"),
            date=str(obj.get("date") or "unknown"),
            chain=str(obj.get("chain") or "ethereum").lower(),
            amount_usd=int(obj.get("amount_usd") or obj.get("amount") or 0),
            attack_type=str(obj.get("attack_type") or obj.get("attack") or "unknown"),
            attacker=str(obj.get("attacker") or "unknown").lower(),
            source=str(obj.get("source") or "manual"),
        )

    @classmethod
    def from_line(cls, line: str) -> "HackRecord | None":
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            return None
        if stripped.startswith("{"):
            return cls.from_obj(json.loads(stripped))
        tx_hash = stripped.split()[0].lower()
        if not TX_HASH_RE.fullmatch(tx_hash):
            return None
        return cls(hash=tx_hash)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class KnownHacksDB:
    """In-memory O(1) index of known exploit transactions."""

    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        self.path = path
        self._index: dict[str, HackRecord] = {}
        self.reload()

    def reload(self) -> None:
        self._index.clear()
        if not self.path.exists():
            log.warning("known hacks file not found: %s", self.path)
            return

        skipped = 0
        for lineno, line in enumerate(self.path.read_text().splitlines(), 1):
            try:
                record = HackRecord.from_line(line)
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                skipped += 1
                log.warning("known hacks line %d skipped: %s", lineno, exc)
                continue
            if record is None:
                if line.strip() and not line.strip().startswith("#"):
                    skipped += 1
                continue
            self._index[record.hash] = record

        log.info("loaded %d known exploit hashes from %s (%d skipped)", len(self._index), self.path, skipped)

    def is_exploit(self, tx_hash: str | None) -> bool:
        return bool(tx_hash) and tx_hash.lower() in self._index

    def get(self, tx_hash: str | None) -> HackRecord | None:
        return self._index.get(tx_hash.lower()) if tx_hash else None

    def all_hashes(self) -> set[str]:
        return set(self._index)

    def append(self, record: HackRecord) -> bool:
        if record.hash in self._index:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as file:
            file.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")
        self._index[record.hash] = record
        return True

    def stats(self) -> dict[str, Any]:
        records = list(self._index.values())
        chains: dict[str, int] = {}
        attack_types: dict[str, int] = {}
        for record in records:
            chains[record.chain] = chains.get(record.chain, 0) + 1
            attack_types[record.attack_type] = attack_types.get(record.attack_type, 0) + 1
        return {
            "total_tx_hashes": len(records),
            "unique_protocols": len({record.protocol for record in records}),
            "total_usd_lost": sum(record.amount_usd for record in records),
            "chains": chains,
            "attack_types": attack_types,
        }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage known_hacks.jsonl")
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    subcommands = parser.add_subparsers(dest="command")

    subcommands.add_parser("stats")

    check = subcommands.add_parser("check")
    check.add_argument("hash")

    list_cmd = subcommands.add_parser("list")
    list_cmd.add_argument("--chain")
    list_cmd.add_argument("--type")
    list_cmd.add_argument("--limit", type=int, default=20)

    add = subcommands.add_parser("add")
    add.add_argument("--hash", required=True)
    add.add_argument("--protocol", required=True)
    add.add_argument("--date", default=datetime.now(UTC).date().isoformat())
    add.add_argument("--chain", default="ethereum")
    add.add_argument("--amount", type=int, default=0)
    add.add_argument("--attack", default="unknown")
    add.add_argument("--attacker", default="unknown")
    add.add_argument("--source", default="manual")
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _build_parser().parse_args()
    db = KnownHacksDB(args.path)

    if args.command in {None, "stats"}:
        print(json.dumps(db.stats(), indent=2, sort_keys=True))
        return

    if args.command == "check":
        record = db.get(args.hash)
        print(json.dumps(record.to_dict(), indent=2, sort_keys=True) if record else "not found")
        return

    if args.command == "list":
        records = sorted(db._index.values(), key=lambda record: record.date, reverse=True)
        if args.chain:
            records = [record for record in records if record.chain == args.chain.lower()]
        if args.type:
            records = [record for record in records if record.attack_type == args.type]
        for record in records[: args.limit]:
            print(json.dumps(record.to_dict(), sort_keys=True))
        return

    if args.command == "add":
        record = HackRecord.from_obj(
            {
                "hash": args.hash,
                "protocol": args.protocol,
                "date": args.date,
                "chain": args.chain,
                "amount_usd": args.amount,
                "attack_type": args.attack,
                "attacker": args.attacker,
                "source": args.source,
            }
        )
        if record is None:
            raise SystemExit("invalid transaction hash")
        print("added" if db.append(record) else "already exists")


if __name__ == "__main__":
    main()
