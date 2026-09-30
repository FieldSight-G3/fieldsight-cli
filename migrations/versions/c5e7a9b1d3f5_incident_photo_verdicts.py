"""incidents keep each photograph's corroboration verdict, so analyze can fire the photo-contradiction trigger

Revision ID: c5e7a9b1d3f5
Revises: b1d4f6a8c2e0
Create Date: 2026-09-30 14:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c5e7a9b1d3f5'
down_revision: str | Sequence[str] | None = 'b1d4f6a8c2e0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("incidents", sa.Column("photo_verdicts", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("incidents", "photo_verdicts")
