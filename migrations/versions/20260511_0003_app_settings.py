"""Add admin-configurable application settings.

Revision ID: 20260511_0003
Revises: 20260511_0002
Create Date: 2026-05-11
"""

from alembic import op


revision = "20260511_0003"
down_revision = "20260511_0002"
branch_labels = None
depends_on = None


DEFAULT_SETTINGS = {
    "risk_alert_threshold": ("70", "int", "Risk score at or above this value creates an alert."),
    "euler_replay_hash": (
        "0xc310a0affe2169d1f6feec1c63dbc7f7c62a887fa48795d327d4d2da2d6b111d",
        "string",
        "Default transaction hash used by the replay demo.",
    ),
    "marketing_transactions_scored": ("11868", "int", "Public marketing counter for transactions scored."),
    "marketing_alerts_fired": ("10832", "int", "Public marketing counter for alerts fired."),
    "marketing_protocols_live": ("5", "int", "Public marketing counter for live protocols."),
    "marketing_alert_latency": ("<3s", "string", "Public marketing copy for alert latency."),
}


def upgrade() -> None:
    op.execute(
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
    for key, (value, value_type, description) in DEFAULT_SETTINGS.items():
        op.execute(
            f"""
            INSERT INTO settings (key, value, value_type, description, is_public)
            VALUES ('{key}', '{value}', '{value_type}', '{description}', TRUE)
            ON CONFLICT (key) DO NOTHING
            """
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS settings")
