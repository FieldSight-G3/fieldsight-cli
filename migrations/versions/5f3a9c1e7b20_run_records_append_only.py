"""run records are append-only; a correction is a new record referencing the original

Revision ID: 5f3a9c1e7b20
Revises: d41e7a0c5b29
Create Date: 2026-09-29 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '5f3a9c1e7b20'
down_revision: str | Sequence[str] | None = 'd41e7a0c5b29'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("run_records", sa.Column("corrects_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("run_records.run_id"), nullable=True))
    op.add_column("run_records", sa.Column("correction_reason", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_run_records_correction_has_reason", "run_records",
        "(corrects_run_id IS NULL) = (correction_reason IS NULL)",
    )
    op.create_index("ix_run_records_corrects_run_id", "run_records", ["corrects_run_id"])
    # enforced in the database, not only in code: no path can edit or delete a recorded run
    op.execute("""
        CREATE FUNCTION run_records_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'run_records is append-only: record a correction referencing run % instead', OLD.run_id
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER run_records_append_only
        BEFORE UPDATE OR DELETE ON run_records
        FOR EACH ROW EXECUTE FUNCTION run_records_append_only()
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS run_records_append_only ON run_records")
    op.execute("DROP FUNCTION IF EXISTS run_records_append_only()")
    op.drop_index("ix_run_records_corrects_run_id", table_name="run_records")
    op.drop_constraint("ck_run_records_correction_has_reason", "run_records", type_="check")
    op.drop_column("run_records", "correction_reason")
    op.drop_column("run_records", "corrects_run_id")
