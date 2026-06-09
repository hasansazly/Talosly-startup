import datetime
import json
from typing import Any

import asyncpg

from backend.config import settings

_pool: asyncpg.Pool | None = None

DEFAULT_APP_SETTINGS: dict[str, dict[str, Any]] = {
    "risk_alert_threshold": {
        "value": "70",
        "value_type": "int",
        "description": "Risk score at or above this value creates an alert.",
        "is_public": True,
    },
    "euler_replay_hash": {
        "value": "0xc310a0affe2169d1f6feec1c63dbc7f7c62a887fa48795d327d4d2da2d6b111d",
        "value_type": "string",
        "description": "Default transaction hash used by the replay demo.",
        "is_public": True,
    },
    "marketing_transactions_scored": {
        "value": "11868",
        "value_type": "int",
        "description": "Public marketing counter for transactions scored.",
        "is_public": True,
    },
    "marketing_alerts_fired": {
        "value": "10832",
        "value_type": "int",
        "description": "Public marketing counter for alerts fired.",
        "is_public": True,
    },
    "marketing_protocols_live": {
        "value": "5",
        "value_type": "int",
        "description": "Public marketing counter for live protocols.",
        "is_public": True,
    },
    "marketing_alert_latency": {
        "value": "<3s",
        "value_type": "string",
        "description": "Public marketing copy for alert latency.",
        "is_public": True,
    },
}


def _record_to_dict(row: asyncpg.Record | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def _parse_setting_value(value: str, value_type: str) -> Any:
    if value_type == "int":
        return int(value)
    if value_type == "float":
        return float(value)
    if value_type == "bool":
        return value.lower() in {"1", "true", "yes", "on"}
    if value_type == "json":
        return json.loads(value)
    return value


def _serialize_setting_value(value: Any, value_type: str) -> str:
    if value_type == "json":
        return json.dumps(value)
    if value_type == "bool":
        return "true" if bool(value) else "false"
    return str(value)


async def init_db() -> None:
    global _pool
    if _pool is None:
        _pool = await _create_preferred_pool()
    await _create_tables()


async def _create_preferred_pool() -> asyncpg.Pool:
    try:
        return await _create_pool(settings.database_url)
    except (OSError, asyncpg.PostgresConnectionError):
        if not settings.database_public_url:
            raise
        return await _create_pool(settings.database_public_url)


async def _create_pool(database_url: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        database_url,
        min_size=1,
        max_size=10,
        command_timeout=30,
    )


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
                last_alert_time TIMESTAMPTZ,
                last_alert_message_id BIGINT,
                alert_batch_count INTEGER NOT NULL DEFAULT 0,
                last_alert_severity TEXT,
                owner_api_key_id INTEGER REFERENCES api_keys(id),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await conn.execute("ALTER TABLE protocols ADD COLUMN IF NOT EXISTS last_alert_time TIMESTAMPTZ")
        await conn.execute("ALTER TABLE protocols ADD COLUMN IF NOT EXISTS last_alert_message_id BIGINT")
        await conn.execute("ALTER TABLE protocols ADD COLUMN IF NOT EXISTS alert_batch_count INTEGER NOT NULL DEFAULT 0")
        await conn.execute("ALTER TABLE protocols ADD COLUMN IF NOT EXISTS last_alert_severity TEXT")
        await conn.execute("ALTER TABLE protocols ADD COLUMN IF NOT EXISTS owner_api_key_id INTEGER")
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
                risk_factors JSONB NOT NULL DEFAULT '[]'::jsonb,
                scored_at TIMESTAMPTZ,
                fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await conn.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS risk_factors JSONB NOT NULL DEFAULT '[]'::jsonb")
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id SERIAL PRIMARY KEY,
                transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
                risk_score INTEGER NOT NULL,
                risk_summary TEXT,
                telegram_sent BOOLEAN NOT NULL DEFAULT FALSE,
                confirmed_threat BOOLEAN,
                feedback_note TEXT,
                reviewed_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await conn.execute("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS confirmed_threat BOOLEAN")
        await conn.execute("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS feedback_note TEXT")
        await conn.execute("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ")
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
                goal TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                api_key_id INTEGER REFERENCES api_keys(id),
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                approved_at TIMESTAMPTZ,
                reviewed_at TIMESTAMPTZ
            )
            """
        )
        await conn.execute(
            """
            ALTER TABLE waitlist
            ADD COLUMN IF NOT EXISTS goal TEXT
            """
        )
        await conn.execute(
            """
            ALTER TABLE waitlist
            ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ
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
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scoring_metrics (
                id SERIAL PRIMARY KEY,
                date DATE NOT NULL UNIQUE,
                total_scored INTEGER NOT NULL DEFAULT 0,
                pre_screened INTEGER NOT NULL DEFAULT 0,
                openai_scored INTEGER NOT NULL DEFAULT 0,
                alerts_fired INTEGER NOT NULL DEFAULT 0,
                avg_score DOUBLE PRECISION NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                value_type TEXT NOT NULL DEFAULT 'string',
                description TEXT,
                is_public BOOLEAN NOT NULL DEFAULT FALSE,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        for key, item in DEFAULT_APP_SETTINGS.items():
            await conn.execute(
                """
                INSERT INTO settings (key, value, value_type, description, is_public)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (key) DO NOTHING
                """,
                key,
                item["value"],
                item["value_type"],
                item["description"],
                item["is_public"],
            )
        await _create_kya_tables(conn)


async def create_kya_tables() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _create_kya_tables(conn)


async def _create_kya_tables(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agents (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            principal_ref TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            owner_api_key_id INTEGER REFERENCES api_keys(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    await conn.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS owner_api_key_id INTEGER")
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_wallets (
            id SERIAL PRIMARY KEY,
            agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            chain TEXT NOT NULL,
            address TEXT NOT NULL UNIQUE,
            added_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_profiles (
            agent_id INTEGER PRIMARY KEY REFERENCES agents(id) ON DELETE CASCADE,
            baseline JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_scores (
            id SERIAL PRIMARY KEY,
            agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            trust_score INTEGER NOT NULL CHECK (trust_score >= 0 AND trust_score <= 100),
            risk_factors JSONB NOT NULL DEFAULT '[]'::jsonb,
            shap_top JSONB NOT NULL DEFAULT '[]'::jsonb,
            confidence DOUBLE PRECISION,
            computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS action_receipts (
            id TEXT PRIMARY KEY,
            version TEXT NOT NULL,
            agent_id INTEGER NOT NULL REFERENCES agents(id),
            action_payload JSONB NOT NULL,
            decision JSONB NOT NULL,
            signals_fired JSONB NOT NULL DEFAULT '[]'::jsonb,
            previous_hash TEXT,
            public_key TEXT NOT NULL,
            created_at TEXT NOT NULL,
            receipt_hash TEXT NOT NULL UNIQUE,
            signature TEXT NOT NULL
        )
        """
    )
    await conn.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_action_receipt_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'action_receipts is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    await conn.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_trigger
                WHERE tgname = 'action_receipts_no_update'
            ) THEN
                CREATE TRIGGER action_receipts_no_update
                BEFORE UPDATE ON action_receipts
                FOR EACH ROW EXECUTE FUNCTION prevent_action_receipt_mutation();
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM pg_trigger
                WHERE tgname = 'action_receipts_no_delete'
            ) THEN
                CREATE TRIGGER action_receipts_no_delete
                BEFORE DELETE ON action_receipts
                FOR EACH ROW EXECUTE FUNCTION prevent_action_receipt_mutation();
            END IF;
        END $$;
        """
    )


async def get_agents_for_owner(owner_api_key_id: int) -> list[dict[str, Any]]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT
            agents.*,
            jsonb_build_object(
                'id', agent_wallets.id,
                'agent_id', agent_wallets.agent_id,
                'chain', agent_wallets.chain,
                'address', agent_wallets.address
            ) AS wallet,
            CASE
                WHEN agent_scores.id IS NULL THEN NULL
                ELSE jsonb_build_object(
                    'id', agent_scores.id,
                    'agent_id', agent_scores.agent_id,
                    'trust_score', agent_scores.trust_score,
                    'risk_factors', agent_scores.risk_factors,
                    'shap_top', agent_scores.shap_top,
                    'confidence', agent_scores.confidence,
                    'computed_at', agent_scores.computed_at
                )
            END AS latest_score,
            CASE
                WHEN agent_profiles.agent_id IS NOT NULL OR agent_scores.id IS NOT NULL THEN 'active'
                ELSE 'pending'
            END AS monitoring_status
        FROM agents
        JOIN agent_wallets ON agent_wallets.agent_id = agents.id
        LEFT JOIN agent_profiles ON agent_profiles.agent_id = agents.id
        LEFT JOIN LATERAL (
            SELECT *
            FROM agent_scores
            WHERE agent_scores.agent_id = agents.id
            ORDER BY computed_at DESC
            LIMIT 1
        ) AS agent_scores ON TRUE
        WHERE agents.owner_api_key_id = $1
        ORDER BY agents.created_at DESC
        """,
        owner_api_key_id,
    )
    return [dict(row) for row in rows]


async def get_agent_for_owner(agent_id: int, owner_api_key_id: int) -> dict[str, Any] | None:
    pool = await get_pool()
    return _record_to_dict(
        await pool.fetchrow(
            "SELECT * FROM agents WHERE id = $1 AND owner_api_key_id = $2",
            agent_id,
            owner_api_key_id,
        )
    )


async def get_agent_score_for_owner(agent_id: int, owner_api_key_id: int) -> dict[str, Any] | None:
    pool = await get_pool()
    return _record_to_dict(
        await pool.fetchrow(
            """
            SELECT agent_scores.id, agent_scores.agent_id, agent_scores.trust_score,
                   agent_scores.risk_factors, agent_scores.shap_top, agent_scores.confidence,
                   agent_scores.computed_at
            FROM agent_scores
            JOIN agents ON agents.id = agent_scores.agent_id
            WHERE agent_scores.agent_id = $1 AND agents.owner_api_key_id = $2
            ORDER BY agent_scores.computed_at DESC
            LIMIT 1
            """,
            agent_id,
            owner_api_key_id,
        )
    )


async def insert_protocol(name: str, address: str, owner_api_key_id: int | None = None) -> int:
    pool = await get_pool()
    return await pool.fetchval(
        "INSERT INTO protocols (name, address, owner_api_key_id) VALUES ($1, $2, $3) RETURNING id",
        name,
        address,
        owner_api_key_id,
    )


async def get_all_protocols(active_only: bool = False, owner_api_key_id: int | None = None) -> list[dict[str, Any]]:
    pool = await get_pool()
    filters = []
    args: list[Any] = []
    if active_only:
        filters.append("is_active = TRUE")
    if owner_api_key_id is not None:
        args.append(owner_api_key_id)
        filters.append(f"owner_api_key_id = ${len(args)}")
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    rows = await pool.fetch(f"SELECT * FROM protocols {where} ORDER BY created_at DESC", *args)
    return [dict(row) for row in rows]


async def get_protocol(protocol_id: int) -> dict[str, Any] | None:
    pool = await get_pool()
    return _record_to_dict(await pool.fetchrow("SELECT * FROM protocols WHERE id = $1", protocol_id))


async def get_protocol_for_owner(protocol_id: int, owner_api_key_id: int) -> dict[str, Any] | None:
    pool = await get_pool()
    return _record_to_dict(
        await pool.fetchrow(
            "SELECT * FROM protocols WHERE id = $1 AND owner_api_key_id = $2",
            protocol_id,
            owner_api_key_id,
        )
    )


async def get_protocol_by_address(address: str) -> dict[str, Any] | None:
    pool = await get_pool()
    return _record_to_dict(await pool.fetchrow("SELECT * FROM protocols WHERE lower(address) = lower($1)", address))


async def delete_protocol(protocol_id: int, owner_api_key_id: int | None = None) -> bool:
    pool = await get_pool()
    if owner_api_key_id is None:
        status = await pool.execute("DELETE FROM protocols WHERE id = $1", protocol_id)
    else:
        status = await pool.execute("DELETE FROM protocols WHERE id = $1 AND owner_api_key_id = $2", protocol_id, owner_api_key_id)
    return status.endswith("1")


async def toggle_protocol(protocol_id: int, owner_api_key_id: int | None = None) -> dict[str, Any] | None:
    pool = await get_pool()
    owner_filter = ""
    args: list[Any] = [protocol_id]
    if owner_api_key_id is not None:
        args.append(owner_api_key_id)
        owner_filter = "AND owner_api_key_id = $2"
    return _record_to_dict(
        await pool.fetchrow(
            f"""
            UPDATE protocols
            SET is_active = NOT is_active
            WHERE id = $1 {owner_filter}
            RETURNING *
            """,
            *args,
        )
    )


async def update_protocol_last_seen(protocol_id: int, block_number: int) -> None:
    pool = await get_pool()
    await pool.execute("UPDATE protocols SET last_seen_block = $1 WHERE id = $2", block_number, protocol_id)


async def get_app_settings(public_only: bool = False) -> dict[str, Any]:
    pool = await get_pool()
    if public_only:
        rows = await pool.fetch("SELECT * FROM settings WHERE is_public = TRUE ORDER BY key")
    else:
        rows = await pool.fetch("SELECT * FROM settings ORDER BY key")
    return {
        row["key"]: _parse_setting_value(row["value"], row["value_type"])
        for row in rows
    }


async def get_app_settings_rows(public_only: bool = False) -> list[dict[str, Any]]:
    pool = await get_pool()
    if public_only:
        rows = await pool.fetch("SELECT * FROM settings WHERE is_public = TRUE ORDER BY key")
    else:
        rows = await pool.fetch("SELECT * FROM settings ORDER BY key")
    result = []
    for row in rows:
        item = dict(row)
        item["parsed_value"] = _parse_setting_value(item["value"], item["value_type"])
        result.append(item)
    return result


async def get_app_setting(key: str, default: Any = None) -> Any:
    pool = await get_pool()
    row = await pool.fetchrow("SELECT value, value_type FROM settings WHERE key = $1", key)
    if not row:
        return default
    return _parse_setting_value(row["value"], row["value_type"])


async def set_app_setting(key: str, value: Any, value_type: str = "string", description: str | None = None, is_public: bool = False) -> dict[str, Any]:
    if value_type not in {"string", "int", "float", "bool", "json"}:
        raise ValueError("Unsupported setting value_type")
    serialized = _serialize_setting_value(value, value_type)
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO settings (key, value, value_type, description, is_public)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (key) DO UPDATE SET
            value = EXCLUDED.value,
            value_type = EXCLUDED.value_type,
            description = COALESCE(EXCLUDED.description, settings.description),
            is_public = EXCLUDED.is_public,
            updated_at = NOW()
        RETURNING *
        """,
        key,
        serialized,
        value_type,
        description,
        is_public,
    )
    item = dict(row)
    item["parsed_value"] = _parse_setting_value(item["value"], item["value_type"])
    return item


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


async def update_transaction_score(tx_id: int, risk_score: int, risk_summary: str, risk_factors: list[str] | None = None) -> None:
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE transactions
        SET risk_score = $1, risk_summary = $2, risk_factors = $3::jsonb, scored_at = NOW()
        WHERE id = $4
        """,
        risk_score,
        risk_summary,
        json.dumps(risk_factors or []),
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


async def submit_alert_feedback(alert_id: int, confirmed_threat: bool, feedback_note: str | None) -> bool:
    pool = await get_pool()
    status = await pool.execute(
        """
        UPDATE alerts
        SET confirmed_threat = $1,
            feedback_note = $2,
            reviewed_at = NOW()
        WHERE id = $3
        """,
        confirmed_threat,
        feedback_note,
        alert_id,
    )
    return status.endswith("1")


async def get_recent_transactions(
    protocol_id: int | None = None,
    limit: int = 50,
    owner_api_key_id: int | None = None,
) -> list[dict[str, Any]]:
    pool = await get_pool()
    limit = min(max(limit, 1), 200)
    filters = []
    args: list[Any] = []
    if protocol_id is not None:
        args.append(protocol_id)
        filters.append(f"transactions.protocol_id = ${len(args)}")
    if owner_api_key_id is not None:
        args.append(owner_api_key_id)
        filters.append(f"protocols.owner_api_key_id = ${len(args)}")
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    args.append(limit)
    rows = await pool.fetch(
        f"""
        SELECT transactions.*
        FROM transactions
        JOIN protocols ON protocols.id = transactions.protocol_id
        {where}
        ORDER BY transactions.fetched_at DESC
        LIMIT ${len(args)}
        """,
        *args,
    )
    return [dict(row) for row in rows]


async def get_transaction_by_hash(tx_hash: str) -> dict[str, Any] | None:
    pool = await get_pool()
    return _record_to_dict(await pool.fetchrow("SELECT * FROM transactions WHERE tx_hash = $1", tx_hash))


async def get_alerts(limit: int = 100, owner_api_key_id: int | None = None) -> list[dict[str, Any]]:
    pool = await get_pool()
    limit = min(max(limit, 1), 500)
    args: list[Any] = []
    owner_filter = ""
    if owner_api_key_id is not None:
        args.append(owner_api_key_id)
        owner_filter = f"WHERE protocols.owner_api_key_id = ${len(args)}"
    args.append(limit)
    rows = await pool.fetch(
        f"""
        SELECT
            alerts.id, alerts.transaction_id, transactions.tx_hash,
            protocols.name AS protocol_name, alerts.risk_score,
            alerts.risk_summary, alerts.telegram_sent, alerts.confirmed_threat,
            alerts.created_at
        FROM alerts
        JOIN transactions ON transactions.id = alerts.transaction_id
        JOIN protocols ON protocols.id = transactions.protocol_id
        {owner_filter}
        ORDER BY alerts.created_at DESC
        LIMIT ${len(args)}
        """,
        *args,
    )
    return [dict(row) for row in rows]


async def get_alert_stats(owner_api_key_id: int | None = None) -> dict[str, int]:
    pool = await get_pool()
    owner_join = ""
    owner_filter = ""
    args: list[Any] = []
    if owner_api_key_id is not None:
        owner_join = """
        JOIN transactions ON transactions.id = alerts.transaction_id
        JOIN protocols ON protocols.id = transactions.protocol_id
        """
        args.append(owner_api_key_id)
        owner_filter = "WHERE protocols.owner_api_key_id = $1"
    row = await pool.fetchrow(
        f"""
        SELECT
            COUNT(*) FILTER (WHERE created_at::date = CURRENT_DATE) AS today,
            COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days') AS this_week,
            COUNT(*) AS all_time
        FROM alerts
        {owner_join}
        {owner_filter}
        """,
        *args,
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


async def insert_waitlist(email: str, name: str | None, project: str | None, twitter: str | None, goal: str | None = None) -> int:
    pool = await get_pool()
    return await pool.fetchval(
        "INSERT INTO waitlist (email, name, project, twitter, goal) VALUES ($1, $2, $3, $4, $5) RETURNING id",
        email,
        name,
        project,
        twitter,
        goal,
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
            SET status = $1,
                api_key_id = COALESCE($2, api_key_id),
                reviewed_at = NOW(),
                approved_at = CASE WHEN $1 = 'approved' THEN NOW() ELSE approved_at END
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


async def get_avg_score_today(protocol_id: int) -> float | None:
    pool = await get_pool()
    avg_score = await pool.fetchval(
        """
        SELECT AVG(risk_score)
        FROM transactions
        WHERE protocol_id = $1
            AND fetched_at::date = CURRENT_DATE
            AND risk_score IS NOT NULL
        """,
        protocol_id,
    )
    return float(avg_score) if avg_score is not None else None


async def get_pre_screened_count_today(protocol_id: int) -> int:
    pool = await get_pool()
    count = await pool.fetchval(
        """
        SELECT COUNT(*)
        FROM transactions
        WHERE protocol_id = $1
            AND fetched_at::date = CURRENT_DATE
            AND risk_factors::text LIKE ANY(ARRAY[
                '%KNOWN_EXPLOIT_CONTRACT%',
                '%LARGE_VALUE_TRANSACTION%',
                '%LARGE_INPUT_DATA%',
                '%PROBE_PATTERN%',
                '%SELF_TRANSFER%'
            ])
        """,
        protocol_id,
    )
    return int(count or 0)


async def upsert_scoring_metrics(
    date: datetime.date,
    total_scored: int,
    pre_screened: int,
    openai_scored: int,
    alerts_fired: int,
    avg_score: float,
) -> None:
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO scoring_metrics
            (date, total_scored, pre_screened, openai_scored, alerts_fired, avg_score)
        VALUES
            ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (date) DO UPDATE SET
            total_scored = scoring_metrics.total_scored + EXCLUDED.total_scored,
            pre_screened = scoring_metrics.pre_screened + EXCLUDED.pre_screened,
            openai_scored = scoring_metrics.openai_scored + EXCLUDED.openai_scored,
            alerts_fired = scoring_metrics.alerts_fired + EXCLUDED.alerts_fired,
            avg_score = EXCLUDED.avg_score
        """,
        date,
        total_scored,
        pre_screened,
        openai_scored,
        alerts_fired,
        avg_score,
    )
