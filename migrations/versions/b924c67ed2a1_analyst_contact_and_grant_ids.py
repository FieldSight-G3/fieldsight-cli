"""Add analyst contact details and grant IDs without dropping existing rows.

Revision ID: b924c67ed2a1
Revises: 83c6ab3f201e
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b924c67ed2a1"
down_revision: str | Sequence[str] | None = "83c6ab3f201e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEED_EMAILS = {
    "seed:alice": "alice@example.invalid",
    "seed:bob": "bob@example.invalid",
    "seed:carol": "carol@example.invalid"
}

def upgrade() -> None:
    connection = op.get_bind()
    old_analysts = sa.table("analysts", sa.column("external_subject", sa.Text()))
    unmapped = connection.execute(
        sa.select(old_analysts.c.external_subject)
        .where(old_analysts.c.external_subject.not_in(list(SEED_EMAILS)))
        .limit(1)
    ).first()
    if unmapped is not None:
        raise RuntimeError("Assign emails to existing non-seed analysts before applying this migration")

    op.alter_column("analysts", "display_name", new_column_name="name")
    op.alter_column("analysts", "external_subject", new_column_name="email")
    op.alter_column("analysts", "analyst_id", server_default=sa.text("gen_random_uuid()"))
    op.add_column(
        "analysts",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))
    )
    analysts = sa.table("analysts", sa.column("email", sa.Text()))
    for old_value, email in SEED_EMAILS.items():
        connection.execute(
            sa.update(analysts).where(analysts.c.email == old_value).values(email=email)
        )

    op.add_column(
        "grants",
        sa.Column("grant_id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"))
    )
    op.add_column(
        "grants",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))
    )
    op.create_unique_constraint("uq_grants_analyst_establishment", "grants", ["analyst_id", "establishment"])
    op.drop_constraint("grants_pkey", "grants", type_="primary")
    op.create_primary_key("grants_pkey", "grants", ["grant_id"])

def downgrade() -> None:
    op.drop_constraint("grants_pkey", "grants", type_="primary")
    op.create_primary_key("grants_pkey", "grants", ["analyst_id", "establishment"])
    op.drop_constraint("uq_grants_analyst_establishment", "grants", type_="unique")
    op.drop_column("grants", "created_at")
    op.drop_column("grants", "grant_id")

    connection = op.get_bind()
    analysts = sa.table("analysts", sa.column("email", sa.Text()))
    for old_value, email in SEED_EMAILS.items():
        connection.execute(
            sa.update(analysts).where(analysts.c.email == email).values(email=old_value)
        )
    op.drop_column("analysts", "created_at")
    op.alter_column("analysts", "analyst_id", server_default=None)
    op.alter_column("analysts", "email", new_column_name="external_subject")
    op.alter_column("analysts", "name", new_column_name="display_name")
