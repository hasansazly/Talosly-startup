"""Add API key ownership to KYA agents.

Revision ID: 20260604_0004
Revises: 20260511_0003
Create Date: 2026-06-04
"""

from alembic import op


revision = "20260604_0004"
down_revision = "20260511_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS owner_api_key_id INTEGER")


def downgrade() -> None:
    pass
