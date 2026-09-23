"""Add analysts, establishment grants and an incident owner.

Revision ID: 83c6ab3f201e
Revises: 7cad869057fa
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "83c6ab3f201e"
down_revision: str | Sequence[str] | None = "7cad869057fa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.create_table(
        "analysts",
        sa.Column("analyst_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_subject", sa.Text(), nullable=False, unique=True),
        sa.Column("display_name", sa.Text(), nullable=False)
    )
    op.create_table(
        "grants",
        sa.Column("analyst_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("analysts.analyst_id"), primary_key=True),
        sa.Column("establishment", sa.Text(), primary_key=True)
    )
    op.add_column(
        "incidents",
        sa.Column("owner_analyst_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_incidents_owner_analyst_id",
        "incidents",
        "analysts",
        ["owner_analyst_id"],
        ["analyst_id"]
    )

def downgrade() -> None:
    op.drop_constraint("fk_incidents_owner_analyst_id", "incidents", type_="foreignkey")
    op.drop_column("incidents", "owner_analyst_id")
    op.drop_table("grants")
    op.drop_table("analysts")
