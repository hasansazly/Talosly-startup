"""Append-only asyncpg persistence for signed action receipts."""

from __future__ import annotations

import json
from typing import Any

import asyncpg


def _row_to_receipt(row: asyncpg.Record | dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    item = dict(row)
    return {
        "id": item["id"],
        "version": item["version"],
        "agent_id": item["agent_id"],
        "action_payload": item["action_payload"],
        "decision": item["decision"],
        "signals_fired": item["signals_fired"],
        "previous_hash": item["previous_hash"],
        "public_key": item["public_key"],
        "created_at": item["created_at"],
        "receipt_hash": item["receipt_hash"],
        "signature": item["signature"],
    }


async def previous_receipt_hash(pool: asyncpg.Pool, agent_id: int) -> str | None:
    return await pool.fetchval(
        """
        SELECT receipt_hash
        FROM action_receipts
        WHERE agent_id = $1
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        agent_id,
    )


async def append_receipt(pool: asyncpg.Pool, receipt: dict[str, Any]) -> dict[str, Any]:
    row = await pool.fetchrow(
        """
        INSERT INTO action_receipts (
            id, version, agent_id, action_payload, decision, signals_fired,
            previous_hash, public_key, created_at, receipt_hash, signature
        )
        VALUES (
            $1, $2, $3, $4::jsonb, $5::jsonb, $6::jsonb,
            $7, $8, $9, $10, $11
        )
        RETURNING *
        """,
        receipt["id"],
        receipt["version"],
        receipt["agent_id"],
        json.dumps(receipt["action_payload"], sort_keys=True),
        json.dumps(receipt["decision"], sort_keys=True),
        json.dumps(receipt["signals_fired"], sort_keys=True),
        receipt["previous_hash"],
        receipt["public_key"],
        receipt["created_at"],
        receipt["receipt_hash"],
        receipt["signature"],
    )
    stored = _row_to_receipt(row)
    assert stored is not None
    return stored


async def list_receipts_for_agent(pool: asyncpg.Pool, agent_id: int, limit: int = 100) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        """
        SELECT *
        FROM action_receipts
        WHERE agent_id = $1
        ORDER BY created_at DESC, id DESC
        LIMIT $2
        """,
        agent_id,
        max(1, min(int(limit), 500)),
    )
    return [receipt for row in rows if (receipt := _row_to_receipt(row)) is not None]


async def get_receipt(pool: asyncpg.Pool, receipt_id: str) -> dict[str, Any] | None:
    return _row_to_receipt(await pool.fetchrow("SELECT * FROM action_receipts WHERE id = $1", receipt_id))


async def get_receipt_for_owner(pool: asyncpg.Pool, receipt_id: str, owner_api_key_id: int) -> dict[str, Any] | None:
    return _row_to_receipt(
        await pool.fetchrow(
            """
            SELECT action_receipts.*
            FROM action_receipts
            JOIN agents ON agents.id = action_receipts.agent_id
            WHERE action_receipts.id = $1
              AND agents.owner_api_key_id = $2
            """,
            receipt_id,
            owner_api_key_id,
        )
    )


__all__ = ["append_receipt", "get_receipt", "get_receipt_for_owner", "list_receipts_for_agent", "previous_receipt_hash"]
