"""Initial Talosly schema.

Revision ID: 20260511_0001
Revises:
Create Date: 2026-05-11
"""

from alembic import op


revision = "20260511_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
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
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("ALTER TABLE protocols ADD COLUMN IF NOT EXISTS last_alert_time TIMESTAMPTZ")
    op.execute("ALTER TABLE protocols ADD COLUMN IF NOT EXISTS last_alert_message_id BIGINT")
    op.execute("ALTER TABLE protocols ADD COLUMN IF NOT EXISTS alert_batch_count INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE protocols ADD COLUMN IF NOT EXISTS last_alert_severity TEXT")
    op.execute(
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
    op.execute("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS risk_factors JSONB NOT NULL DEFAULT '[]'::jsonb")
    op.execute(
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
    op.execute("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS confirmed_threat BOOLEAN")
    op.execute("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS feedback_note TEXT")
    op.execute("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ")
    op.execute(
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
    op.execute(
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
    op.execute("ALTER TABLE waitlist ADD COLUMN IF NOT EXISTS goal TEXT")
    op.execute("ALTER TABLE waitlist ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ")
    op.execute(
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
    op.execute(
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
    op.execute(
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


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS scoring_metrics")
    op.execute("DROP TABLE IF EXISTS request_log")
    op.execute("DROP TABLE IF EXISTS waitlist")
    op.execute("DROP TABLE IF EXISTS api_keys")
    op.execute("DROP TABLE IF EXISTS alerts")
    op.execute("DROP TABLE IF EXISTS transactions")
    op.execute("DROP TABLE IF EXISTS protocols")
