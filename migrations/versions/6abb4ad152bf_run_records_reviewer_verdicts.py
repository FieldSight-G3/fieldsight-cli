"""run_records reviewer_verdicts

Revision ID: 6abb4ad152bf
Revises: d41e7a0c5b29
Create Date: 2026-09-29 21:26:05.165424

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '6abb4ad152bf'
down_revision: str | Sequence[str] | None = "5f3a9c1e7b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("run_records", sa.Column("reviewer_verdicts", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("run_records", "reviewer_verdicts")
