from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

import aiosqlite

from backend.config import settings

_memory_db: Optional[aiosqlite.Connection] = None


def _row_to_dict(row: aiosqlite.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


async def _connect() -> aiosqlite.Connection:
    global _memory_db
    if settings.database_path == ":memory:":
        if _memory_db is None:
            _memory_db = await aiosqlite.connect(":memory:")
            _memory_db.row_factory = aiosqlite.Row
        return _memory_db
    conn = await aiosqlite.connect(settings.database_path)
    conn.row_factory = aiosqlite.Row
    return conn


@asynccontextmanager
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    conn = await _connect()
    try:
        yield conn
        await conn.commit()
    finally:
        if settings.database_path != ":memory:":
            await conn.close()


async def init_db() -> None:
    async with get_db() as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS protocols (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                address TEXT NOT NULL UNIQUE,
                chain TEXT NOT NULL DEFAULT 'ethereum',
                is_active INTEGER NOT NULL DEFAULT 1,
                last_seen_block INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                protocol_id INTEGER NOT NULL REFERENCES protocols(id),
                tx_hash TEXT NOT NULL UNIQUE,
                block_number INTEGER,
                from_address TEXT,
                to_address TEXT,
                value_eth REAL,
                gas_used INTEGER,
                input_data TEXT,
                risk_score INTEGER,
                risk_summary TEXT,
                scored_at TEXT,
                fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id INTEGER NOT NULL REFERENCES transactions(id),
                risk_score INTEGER NOT NULL,
                risk_summary TEXT,
                telegram_sent INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )


async def insert_protocol(name: str, address: str) -> int:
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO protocols (name, address) VALUES (?, ?)",
            (name, address),
        )
        return int(cursor.lastrowid)


async def get_all_protocols(active_only: bool = False) -> list[dict[str, Any]]:
    query = "SELECT * FROM protocols"
    params: tuple[Any, ...] = ()
    if active_only:
        query += " WHERE is_active = ?"
        params = (1,)
    query += " ORDER BY created_at DESC"
    async with get_db() as db:
        cursor = await db.execute(query, params)
        return [dict(row) async for row in cursor]


async def get_protocol(protocol_id: int) -> dict[str, Any] | None:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM protocols WHERE id = ?", (protocol_id,))
        return _row_to_dict(await cursor.fetchone())


async def get_protocol_by_address(address: str) -> dict[str, Any] | None:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM protocols WHERE lower(address) = lower(?)", (address,))
        return _row_to_dict(await cursor.fetchone())


async def delete_protocol(protocol_id: int) -> bool:
    async with get_db() as db:
        cursor = await db.execute("DELETE FROM protocols WHERE id = ?", (protocol_id,))
        return cursor.rowcount > 0


async def toggle_protocol(protocol_id: int) -> dict[str, Any] | None:
    async with get_db() as db:
        await db.execute(
            "UPDATE protocols SET is_active = CASE is_active WHEN 1 THEN 0 ELSE 1 END WHERE id = ?",
            (protocol_id,),
        )
        cursor = await db.execute("SELECT * FROM protocols WHERE id = ?", (protocol_id,))
        return _row_to_dict(await cursor.fetchone())


async def update_protocol_last_seen(protocol_id: int, block_number: int) -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE protocols SET last_seen_block = ? WHERE id = ?",
            (block_number, protocol_id),
        )


async def upsert_transaction(protocol_id: int, tx_data_dict: dict[str, Any]) -> tuple[int, bool]:
    async with get_db() as db:
        cursor = await db.execute("SELECT id FROM transactions WHERE tx_hash = ?", (tx_data_dict["tx_hash"],))
        existing = await cursor.fetchone()
        if existing:
            return int(existing["id"]), False
        cursor = await db.execute(
            """
            INSERT INTO transactions (
                protocol_id, tx_hash, block_number, from_address, to_address,
                value_eth, gas_used, input_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                protocol_id,
                tx_data_dict["tx_hash"],
                tx_data_dict.get("block_number"),
                tx_data_dict.get("from_address"),
                tx_data_dict.get("to_address"),
                tx_data_dict.get("value_eth"),
                tx_data_dict.get("gas_used"),
                (tx_data_dict.get("input_data") or "")[:500],
            ),
        )
        return int(cursor.lastrowid), True


async def update_transaction_score(tx_id: int, risk_score: int, risk_summary: str) -> None:
    async with get_db() as db:
        await db.execute(
            """
            UPDATE transactions
            SET risk_score = ?, risk_summary = ?, scored_at = datetime('now')
            WHERE id = ?
            """,
            (risk_score, risk_summary, tx_id),
        )


async def insert_alert(transaction_id: int, risk_score: int, risk_summary: str) -> int:
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO alerts (transaction_id, risk_score, risk_summary) VALUES (?, ?, ?)",
            (transaction_id, risk_score, risk_summary),
        )
        return int(cursor.lastrowid)


async def mark_telegram_sent(alert_id: int) -> None:
    async with get_db() as db:
        await db.execute("UPDATE alerts SET telegram_sent = 1 WHERE id = ?", (alert_id,))


async def get_recent_transactions(protocol_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
    limit = min(max(limit, 1), 200)
    params: tuple[Any, ...]
    query = "SELECT * FROM transactions"
    if protocol_id is not None:
        query += " WHERE protocol_id = ?"
        params = (protocol_id, limit)
    else:
        params = (limit,)
    query += " ORDER BY fetched_at DESC LIMIT ?"
    async with get_db() as db:
        cursor = await db.execute(query, params)
        return [dict(row) async for row in cursor]


async def get_transaction_by_hash(tx_hash: str) -> dict[str, Any] | None:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM transactions WHERE tx_hash = ?", (tx_hash,))
        return _row_to_dict(await cursor.fetchone())


async def get_alerts(limit: int = 100) -> list[dict[str, Any]]:
    limit = min(max(limit, 1), 500)
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT
                alerts.id, alerts.transaction_id, transactions.tx_hash,
                protocols.name AS protocol_name, alerts.risk_score,
                alerts.risk_summary, alerts.telegram_sent, alerts.created_at
            FROM alerts
            JOIN transactions ON transactions.id = alerts.transaction_id
            JOIN protocols ON protocols.id = transactions.protocol_id
            ORDER BY alerts.created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) async for row in cursor]


async def get_alert_stats() -> dict[str, int]:
    async with get_db() as db:
        today = await (await db.execute("SELECT COUNT(*) AS count FROM alerts WHERE date(created_at) = date('now')")).fetchone()
        week = await (await db.execute("SELECT COUNT(*) AS count FROM alerts WHERE created_at >= datetime('now', '-7 days')")).fetchone()
        total = await (await db.execute("SELECT COUNT(*) AS count FROM alerts")).fetchone()
        return {"today": today["count"], "this_week": week["count"], "all_time": total["count"]}
