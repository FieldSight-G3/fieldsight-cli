"""run records keep the dossier the turn showed, so dossier and sources can read it after analyze exits

Revision ID: a7c3e9d1f2b4
Revises: 6abb4ad152bf
Create Date: 2026-09-30 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a7c3e9d1f2b4'
down_revision: str | Sequence[str] | None = '6abb4ad152bf'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("run_records", sa.Column("dossier", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("run_records", "dossier")
