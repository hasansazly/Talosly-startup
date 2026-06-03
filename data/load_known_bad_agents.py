"""Load known bad autonomous agent identifiers for offline KYA training."""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_PATH = Path(__file__).with_name("known_bad_agents.jsonl")


@dataclass(frozen=True)
class BadAgentRecord:
    agent_id: str
    principal_ref: str = ""
    wallet: str = ""
    chain: str = "ethereum"
    date: str = "unknown"
    reason: str = "unknown"
    source: str = "manual"

    @classmethod
    def from_obj(cls, obj: dict[str, Any]) -> "BadAgentRecord | None":
        agent_id = str(obj.get("agent_id") or obj.get("id") or "").strip()
        principal_ref = str(obj.get("principal_ref") or "").strip()
        wallet = str(obj.get("wallet") or obj.get("address") or "").lower().strip()
        if not agent_id and not principal_ref and not wallet:
            return None
        return cls(
            agent_id=agent_id or principal_ref or wallet,
            principal_ref=principal_ref,
            wallet=wallet,
            chain=str(obj.get("chain") or "ethereum").lower(),
            date=str(obj.get("date") or "unknown"),
            reason=str(obj.get("reason") or obj.get("label") or "unknown"),
            source=str(obj.get("source") or "manual"),
        )

    @classmethod
    def from_line(cls, line: str) -> "BadAgentRecord | None":
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            return None
        if stripped.startswith("{"):
            return cls.from_obj(json.loads(stripped))
        return cls(agent_id=stripped.split()[0])

    def keys(self) -> set[str]:
        return {item.lower() for item in (self.agent_id, self.principal_ref, self.wallet) if item}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class KnownBadAgentsDB:
    """In-memory O(1) index of known bad agent identifiers."""

    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        self.path = path
        self._index: dict[str, BadAgentRecord] = {}
        self.reload()

    def reload(self) -> None:
        self._index.clear()
        if not self.path.exists():
            log.warning("known bad agents file not found: %s", self.path)
            return

        skipped = 0
        for lineno, line in enumerate(self.path.read_text().splitlines(), 1):
            try:
                record = BadAgentRecord.from_line(line)
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                skipped += 1
                log.warning("known bad agents line %d skipped: %s", lineno, exc)
                continue
            if record is None:
                if line.strip() and not line.strip().startswith("#"):
                    skipped += 1
                continue
            for key in record.keys():
                self._index[key] = record

        log.info("loaded %d known bad agent keys from %s (%d skipped)", len(self._index), self.path, skipped)

    def is_bad(self, *identifiers: Any) -> bool:
        return any(str(identifier).lower() in self._index for identifier in identifiers if identifier)

    def get(self, identifier: Any) -> BadAgentRecord | None:
        return self._index.get(str(identifier).lower()) if identifier else None

    def append(self, record: BadAgentRecord) -> bool:
        if any(key in self._index for key in record.keys()):
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")
        for key in record.keys():
            self._index[key] = record
        return True

    def stats(self) -> dict[str, Any]:
        records = {id(record): record for record in self._index.values()}.values()
        return {
            "total_keys": len(self._index),
            "unique_agents": len(list(records)),
        }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage known_bad_agents.jsonl")
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("stats")

    check = subcommands.add_parser("check")
    check.add_argument("identifier")

    add = subcommands.add_parser("add")
    add.add_argument("--agent-id", required=True)
    add.add_argument("--principal-ref", default="")
    add.add_argument("--wallet", default="")
    add.add_argument("--chain", default="ethereum")
    add.add_argument("--date", default=datetime.now(UTC).date().isoformat())
    add.add_argument("--reason", default="unknown")
    add.add_argument("--source", default="manual")
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _build_parser().parse_args()
    db = KnownBadAgentsDB(args.path)

    if args.command in {None, "stats"}:
        print(json.dumps(db.stats(), indent=2, sort_keys=True))
        return
    if args.command == "check":
        record = db.get(args.identifier)
        print(json.dumps(record.to_dict(), indent=2, sort_keys=True) if record else "not found")
        return
    if args.command == "add":
        record = BadAgentRecord(
            agent_id=args.agent_id,
            principal_ref=args.principal_ref,
            wallet=args.wallet.lower(),
            chain=args.chain.lower(),
            date=args.date,
            reason=args.reason,
            source=args.source,
        )
        print("added" if db.append(record) else "already exists")


if __name__ == "__main__":
    main()
