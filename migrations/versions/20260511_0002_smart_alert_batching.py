"""Add smart alert batching state.

Revision ID: 20260511_0002
Revises: 20260511_0001
Create Date: 2026-05-11
"""

from alembic import op


revision = "20260511_0002"
down_revision = "20260511_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE protocols ADD COLUMN IF NOT EXISTS last_alert_time TIMESTAMPTZ")
    op.execute("ALTER TABLE protocols ADD COLUMN IF NOT EXISTS last_alert_message_id BIGINT")
    op.execute("ALTER TABLE protocols ADD COLUMN IF NOT EXISTS alert_batch_count INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE protocols ADD COLUMN IF NOT EXISTS last_alert_severity TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE protocols DROP COLUMN IF EXISTS last_alert_severity")
    op.execute("ALTER TABLE protocols DROP COLUMN IF EXISTS alert_batch_count")
    op.execute("ALTER TABLE protocols DROP COLUMN IF EXISTS last_alert_message_id")
    op.execute("ALTER TABLE protocols DROP COLUMN IF EXISTS last_alert_time")
