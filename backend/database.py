from typing import Any

import asyncpg

from backend.config import settings

_pool: asyncpg.Pool | None = None


def _record_to_dict(row: asyncpg.Record | None) -> dict[str, Any] | None:
    return dict(row) if row else None


async def init_db() -> None:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=1,
            max_size=10,
            command_timeout=30,
        )
    await _create_tables()


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def get_pool() -> asyncpg.Pool:
    if _pool is None:
        await init_db()
    assert _pool is not None
    return _pool


async def _create_tables() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS protocols (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                address TEXT NOT NULL UNIQUE,
                chain TEXT NOT NULL DEFAULT 'ethereum',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                last_seen_block INTEGER,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                protocol_id INTEGER NOT NULL REFERENCES protocols(id) ON DELETE CASCADE,
                tx_hash TEXT NOT NULL UNIQUE,
                block_number INTEGER,
                from_address TEXT,
                to_address TEXT,
                value_eth DOUBLE PRECISION,
                gas_used INTEGER,
                input_data TEXT,
                risk_score INTEGER,
                risk_summary TEXT,
                scored_at TIMESTAMPTZ,
                fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id SERIAL PRIMARY KEY,
                transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
                risk_score INTEGER NOT NULL,
                risk_summary TEXT,
                telegram_sent BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                id SERIAL PRIMARY KEY,
                key_hash TEXT NOT NULL UNIQUE,
                key_prefix TEXT NOT NULL,
                name TEXT,
                waitlist_id INTEGER,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                requests_today INTEGER NOT NULL DEFAULT 0,
                requests_total INTEGER NOT NULL DEFAULT 0,
                last_used_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS waitlist (
                id SERIAL PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                name TEXT,
                project TEXT,
                twitter TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                api_key_id INTEGER REFERENCES api_keys(id),
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                reviewed_at TIMESTAMPTZ
            )
            """
        )
        await conn.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = 'api_keys_waitlist_id_fkey'
                    AND table_name = 'api_keys'
                ) THEN
                    ALTER TABLE api_keys
                    ADD CONSTRAINT api_keys_waitlist_id_fkey
                    FOREIGN KEY (waitlist_id) REFERENCES waitlist(id);
                END IF;
            END $$;
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS request_log (
                id SERIAL PRIMARY KEY,
                api_key_id INTEGER REFERENCES api_keys(id),
                endpoint TEXT NOT NULL,
                method TEXT NOT NULL,
                status_code INTEGER,
                response_ms INTEGER,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )


async def insert_protocol(name: str, address: str) -> int:
    pool = await get_pool()
    return await pool.fetchval("INSERT INTO protocols (name, address) VALUES ($1, $2) RETURNING id", name, address)


async def get_all_protocols(active_only: bool = False) -> list[dict[str, Any]]:
    pool = await get_pool()
    if active_only:
        rows = await pool.fetch("SELECT * FROM protocols WHERE is_active = TRUE ORDER BY created_at DESC")
    else:
        rows = await pool.fetch("SELECT * FROM protocols ORDER BY created_at DESC")
    return [dict(row) for row in rows]


async def get_protocol(protocol_id: int) -> dict[str, Any] | None:
    pool = await get_pool()
    return _record_to_dict(await pool.fetchrow("SELECT * FROM protocols WHERE id = $1", protocol_id))


async def get_protocol_by_address(address: str) -> dict[str, Any] | None:
    pool = await get_pool()
    return _record_to_dict(await pool.fetchrow("SELECT * FROM protocols WHERE lower(address) = lower($1)", address))


async def delete_protocol(protocol_id: int) -> bool:
    pool = await get_pool()
    status = await pool.execute("DELETE FROM protocols WHERE id = $1", protocol_id)
    return status.endswith("1")


async def toggle_protocol(protocol_id: int) -> dict[str, Any] | None:
    pool = await get_pool()
    return _record_to_dict(
        await pool.fetchrow(
            """
            UPDATE protocols
            SET is_active = NOT is_active
            WHERE id = $1
            RETURNING *
            """,
            protocol_id,
        )
    )


async def update_protocol_last_seen(protocol_id: int, block_number: int) -> None:
    pool = await get_pool()
    await pool.execute("UPDATE protocols SET last_seen_block = $1 WHERE id = $2", block_number, protocol_id)


async def upsert_transaction(protocol_id: int, tx_data_dict: dict[str, Any]) -> tuple[int, bool]:
    pool = await get_pool()
    existing = await pool.fetchrow("SELECT id FROM transactions WHERE tx_hash = $1", tx_data_dict["tx_hash"])
    if existing:
        return int(existing["id"]), False
    tx_id = await pool.fetchval(
        """
        INSERT INTO transactions (
            protocol_id, tx_hash, block_number, from_address, to_address,
            value_eth, gas_used, input_data
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id
        """,
        protocol_id,
        tx_data_dict["tx_hash"],
        tx_data_dict.get("block_number"),
        tx_data_dict.get("from_address"),
        tx_data_dict.get("to_address"),
        tx_data_dict.get("value_eth"),
        tx_data_dict.get("gas_used"),
        (tx_data_dict.get("input_data") or "")[:500],
    )
    return int(tx_id), True


async def update_transaction_score(tx_id: int, risk_score: int, risk_summary: str) -> None:
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE transactions
        SET risk_score = $1, risk_summary = $2, scored_at = NOW()
        WHERE id = $3
        """,
        risk_score,
        risk_summary,
        tx_id,
    )


async def insert_alert(transaction_id: int, risk_score: int, risk_summary: str) -> int:
    pool = await get_pool()
    return await pool.fetchval(
        "INSERT INTO alerts (transaction_id, risk_score, risk_summary) VALUES ($1, $2, $3) RETURNING id",
        transaction_id,
        risk_score,
        risk_summary,
    )


async def mark_telegram_sent(alert_id: int) -> None:
    pool = await get_pool()
    await pool.execute("UPDATE alerts SET telegram_sent = TRUE WHERE id = $1", alert_id)


async def get_recent_transactions(protocol_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
    pool = await get_pool()
    limit = min(max(limit, 1), 200)
    if protocol_id is not None:
        rows = await pool.fetch(
            "SELECT * FROM transactions WHERE protocol_id = $1 ORDER BY fetched_at DESC LIMIT $2",
            protocol_id,
            limit,
        )
    else:
        rows = await pool.fetch("SELECT * FROM transactions ORDER BY fetched_at DESC LIMIT $1", limit)
    return [dict(row) for row in rows]


async def get_transaction_by_hash(tx_hash: str) -> dict[str, Any] | None:
    pool = await get_pool()
    return _record_to_dict(await pool.fetchrow("SELECT * FROM transactions WHERE tx_hash = $1", tx_hash))


async def get_alerts(limit: int = 100) -> list[dict[str, Any]]:
    pool = await get_pool()
    limit = min(max(limit, 1), 500)
    rows = await pool.fetch(
        """
        SELECT
            alerts.id, alerts.transaction_id, transactions.tx_hash,
            protocols.name AS protocol_name, alerts.risk_score,
            alerts.risk_summary, alerts.telegram_sent, alerts.created_at
        FROM alerts
        JOIN transactions ON transactions.id = alerts.transaction_id
        JOIN protocols ON protocols.id = transactions.protocol_id
        ORDER BY alerts.created_at DESC
        LIMIT $1
        """,
        limit,
    )
    return [dict(row) for row in rows]


async def get_alert_stats() -> dict[str, int]:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (WHERE created_at::date = CURRENT_DATE) AS today,
            COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days') AS this_week,
            COUNT(*) AS all_time
        FROM alerts
        """
    )
    return {"today": row["today"], "this_week": row["this_week"], "all_time": row["all_time"]}


async def find_api_key_by_hash(key_hash: str) -> dict[str, Any] | None:
    pool = await get_pool()
    return _record_to_dict(await pool.fetchrow("SELECT * FROM api_keys WHERE key_hash = $1 AND is_active = TRUE", key_hash))


async def create_api_key(key_hash: str, key_prefix: str, name: str | None = None, waitlist_id: int | None = None) -> int:
    pool = await get_pool()
    return await pool.fetchval(
        """
        INSERT INTO api_keys (key_hash, key_prefix, name, waitlist_id)
        VALUES ($1, $2, $3, $4)
        RETURNING id
        """,
        key_hash,
        key_prefix,
        name,
        waitlist_id,
    )


async def update_key_usage(api_key_id: int) -> None:
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE api_keys
        SET requests_today = requests_today + 1,
            requests_total = requests_total + 1,
            last_used_at = NOW()
        WHERE id = $1
        """,
        api_key_id,
    )


async def list_api_keys() -> list[dict[str, Any]]:
    pool = await get_pool()
    rows = await pool.fetch("SELECT id, key_prefix, name, is_active, requests_today, requests_total, last_used_at, created_at FROM api_keys ORDER BY created_at DESC")
    return [dict(row) for row in rows]


async def revoke_api_key(api_key_id: int) -> bool:
    pool = await get_pool()
    status = await pool.execute("UPDATE api_keys SET is_active = FALSE WHERE id = $1", api_key_id)
    return status.endswith("1")


async def insert_waitlist(email: str, name: str | None, project: str | None, twitter: str | None) -> int:
    pool = await get_pool()
    return await pool.fetchval(
        "INSERT INTO waitlist (email, name, project, twitter) VALUES ($1, $2, $3, $4) RETURNING id",
        email,
        name,
        project,
        twitter,
    )


async def get_waitlist_by_email(email: str) -> dict[str, Any] | None:
    pool = await get_pool()
    return _record_to_dict(await pool.fetchrow("SELECT * FROM waitlist WHERE lower(email) = lower($1)", email))


async def list_waitlist() -> list[dict[str, Any]]:
    pool = await get_pool()
    rows = await pool.fetch("SELECT * FROM waitlist ORDER BY applied_at DESC")
    return [dict(row) for row in rows]


async def set_waitlist_status(waitlist_id: int, status: str, api_key_id: int | None = None) -> dict[str, Any] | None:
    pool = await get_pool()
    return _record_to_dict(
        await pool.fetchrow(
            """
            UPDATE waitlist
            SET status = $1, api_key_id = COALESCE($2, api_key_id), reviewed_at = NOW()
            WHERE id = $3
            RETURNING *
            """,
            status,
            api_key_id,
            waitlist_id,
        )
    )


async def log_request(api_key_id: int | None, endpoint: str, method: str, status_code: int, response_ms: int) -> None:
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO request_log (api_key_id, endpoint, method, status_code, response_ms) VALUES ($1, $2, $3, $4, $5)",
        api_key_id,
        endpoint,
        method,
        status_code,
        response_ms,
    )


async def get_public_stats() -> dict[str, int]:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT
            (SELECT COUNT(*) FROM protocols WHERE is_active = TRUE) AS protocols_monitored,
            (SELECT COUNT(*) FROM transactions WHERE risk_score IS NOT NULL) AS transactions_scored,
            (SELECT COUNT(*) FROM alerts) AS alerts_fired
        """
    )
    return {
        "protocols_monitored": row["protocols_monitored"],
        "transactions_scored": row["transactions_scored"],
        "alerts_fired": row["alerts_fired"],
        "uptime_days": 1,
    }


async def get_admin_metrics() -> dict[str, Any]:
    pool = await get_pool()
    overview = await pool.fetchrow(
        """
        SELECT
            (SELECT COUNT(*) FROM api_keys) AS total_api_keys,
            (SELECT COUNT(*) FROM api_keys WHERE is_active = TRUE) AS active_api_keys,
            (SELECT COUNT(*) FROM waitlist WHERE status = 'pending') AS waitlist_pending,
            (SELECT COUNT(*) FROM protocols) AS protocols_monitored,
            (SELECT COUNT(*) FROM transactions WHERE risk_score IS NOT NULL) AS transactions_scored_total,
            (SELECT COUNT(*) FROM alerts) AS alerts_fired_total,
            (SELECT COUNT(*) FROM request_log WHERE created_at::date = CURRENT_DATE) AS requests_today
        """
    )
    top_keys = await pool.fetch(
        """
        SELECT key_prefix, name, requests_today
        FROM api_keys
        ORDER BY requests_today DESC
        LIMIT 10
        """
    )
    daily = await pool.fetch(
        """
        SELECT day::date AS date, COUNT(request_log.id) AS requests
        FROM generate_series(CURRENT_DATE - INTERVAL '6 days', CURRENT_DATE, INTERVAL '1 day') AS day
        LEFT JOIN request_log ON request_log.created_at::date = day::date
        GROUP BY day
        ORDER BY day
        """
    )
    distribution = await pool.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (WHERE risk_score BETWEEN 0 AND 30) AS low_0_30,
            COUNT(*) FILTER (WHERE risk_score BETWEEN 31 AND 60) AS medium_31_60,
            COUNT(*) FILTER (WHERE risk_score BETWEEN 61 AND 70) AS elevated_61_70,
            COUNT(*) FILTER (WHERE risk_score BETWEEN 71 AND 100) AS high_71_100
        FROM transactions
        WHERE risk_score IS NOT NULL
        """
    )
    return {
        "overview": dict(overview),
        "top_keys_by_usage": [dict(row) for row in top_keys],
        "daily_requests_last_7_days": [{"date": str(row["date"]), "requests": row["requests"]} for row in daily],
        "risk_score_distribution": dict(distribution),
    }
