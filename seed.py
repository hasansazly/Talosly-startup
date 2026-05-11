import asyncio
import json
from pathlib import Path
from typing import Any

import asyncpg
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "seed_data.json"
load_dotenv(BASE_DIR / ".env")

from backend.database import close_db, get_pool, init_db  # noqa: E402


def load_seed_data() -> dict[str, Any]:
    with DATA_FILE.open(encoding="utf-8") as file:
        return json.load(file)


async def upsert_protocol(conn: asyncpg.Connection, protocol: dict[str, Any]) -> int:
    return await conn.fetchval(
        """
        INSERT INTO protocols (name, address, chain, is_active, last_seen_block)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (address) DO UPDATE
        SET name = EXCLUDED.name,
            chain = EXCLUDED.chain,
            is_active = EXCLUDED.is_active,
            last_seen_block = EXCLUDED.last_seen_block
        RETURNING id
        """,
        protocol["name"],
        protocol["address"],
        protocol.get("chain", "ethereum"),
        protocol.get("is_active", True),
        protocol.get("last_seen_block"),
    )


async def upsert_transaction(conn: asyncpg.Connection, protocol_id: int, tx: dict[str, Any]) -> int:
    return await conn.fetchval(
        """
        INSERT INTO transactions (
            protocol_id, tx_hash, block_number, from_address, to_address,
            value_eth, gas_used, input_data, risk_score, risk_summary,
            risk_factors, scored_at
        )
        VALUES (
            $1::int, $2::text, $3::int, $4::text, $5::text,
            $6::double precision, $7::int, $8::text, $9::int, $10::text,
            $11::jsonb, CASE WHEN $9::int IS NULL THEN NULL ELSE NOW() END
        )
        ON CONFLICT (tx_hash) DO UPDATE
        SET protocol_id = EXCLUDED.protocol_id,
            block_number = EXCLUDED.block_number,
            from_address = EXCLUDED.from_address,
            to_address = EXCLUDED.to_address,
            value_eth = EXCLUDED.value_eth,
            gas_used = EXCLUDED.gas_used,
            input_data = EXCLUDED.input_data,
            risk_score = EXCLUDED.risk_score,
            risk_summary = EXCLUDED.risk_summary,
            risk_factors = EXCLUDED.risk_factors,
            scored_at = EXCLUDED.scored_at
        RETURNING id
        """,
        protocol_id,
        tx["tx_hash"],
        tx.get("block_number"),
        tx.get("from_address"),
        tx.get("to_address"),
        tx.get("value_eth"),
        tx.get("gas_used"),
        tx.get("input_data", "")[:500],
        tx.get("risk_score"),
        tx.get("risk_summary"),
        json.dumps(tx.get("risk_factors", [])),
    )


async def upsert_alert(conn: asyncpg.Connection, transaction_id: int, tx: dict[str, Any]) -> None:
    alert = tx.get("alert")
    if not alert:
        return

    existing_id = await conn.fetchval(
        "SELECT id FROM alerts WHERE transaction_id = $1",
        transaction_id,
    )
    if existing_id:
        await conn.execute(
            """
            UPDATE alerts
            SET risk_score = $1,
                risk_summary = $2,
                telegram_sent = $3,
                confirmed_threat = $4,
                feedback_note = $5
            WHERE id = $6
            """,
            tx.get("risk_score", 0),
            tx.get("risk_summary"),
            alert.get("telegram_sent", False),
            alert.get("confirmed_threat"),
            alert.get("feedback_note"),
            existing_id,
        )
        return

    await conn.execute(
        """
        INSERT INTO alerts (
            transaction_id, risk_score, risk_summary, telegram_sent,
            confirmed_threat, feedback_note
        )
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        transaction_id,
        tx.get("risk_score", 0),
        tx.get("risk_summary"),
        alert.get("telegram_sent", False),
        alert.get("confirmed_threat"),
        alert.get("feedback_note"),
    )


async def upsert_waitlist(conn: asyncpg.Connection, applicant: dict[str, Any]) -> None:
    await conn.execute(
        """
        INSERT INTO waitlist (email, name, project, twitter, goal)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (email) DO UPDATE
        SET name = EXCLUDED.name,
            project = EXCLUDED.project,
            twitter = EXCLUDED.twitter,
            goal = EXCLUDED.goal
        """,
        applicant["email"],
        applicant.get("name"),
        applicant.get("project"),
        applicant.get("twitter"),
        applicant.get("goal"),
    )


async def main() -> None:
    data = load_seed_data()

    await init_db()
    pool = await get_pool()

    async with pool.acquire() as conn:
        async with conn.transaction():
            for protocol in data.get("protocols", []):
                protocol_id = await upsert_protocol(conn, protocol)
                for tx in protocol.get("transactions", []):
                    tx_id = await upsert_transaction(conn, protocol_id, tx)
                    await upsert_alert(conn, tx_id, tx)

            for applicant in data.get("waitlist", []):
                await upsert_waitlist(conn, applicant)

    await close_db()
    print(f"Seeded database from {DATA_FILE.name}")


if __name__ == "__main__":
    asyncio.run(main())
