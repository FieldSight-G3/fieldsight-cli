"""sessions keep the dollars spent, so the per-incident cost ceiling accumulates across commands

Revision ID: d8f0b2c4e6a7
Revises: c5e7a9b1d3f5
Create Date: 2026-09-30 18:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd8f0b2c4e6a7'
down_revision: str | Sequence[str] | None = 'c5e7a9b1d3f5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("sessions", sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("sessions", "cost_usd")
