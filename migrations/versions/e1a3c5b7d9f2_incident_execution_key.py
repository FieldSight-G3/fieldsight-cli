"""incidents keep the idempotency key of the write after approval, so a retried execution applies once

Revision ID: e1a3c5b7d9f2
Revises: d8f0b2c4e6a7
Create Date: 2026-09-30 19:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e1a3c5b7d9f2'
down_revision: str | Sequence[str] | None = 'd8f0b2c4e6a7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("incidents", sa.Column("execution_key", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_unique_constraint("uq_incidents_execution_key", "incidents", ["execution_key"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_incidents_execution_key", "incidents", type_="unique")
    op.drop_column("incidents", "execution_key")
