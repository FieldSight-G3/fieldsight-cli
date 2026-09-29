"""add analyst iam role arn

Revision ID: c93a06b2aade
Revises: b924c67ed2a1
Create Date: 2026-09-27 17:09:20.659274

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c93a06b2aade'
down_revision: str | Sequence[str] | None = 'b924c67ed2a1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("analysts", sa.Column("iam_role_arn", sa.Text(), nullable=True))
    op.create_unique_constraint("uq_analysts_iam_role_arn", "analysts", ["iam_role_arn"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_analysts_iam_role_arn", "analysts", type_="unique")
    op.drop_column("analysts", "iam_role_arn")