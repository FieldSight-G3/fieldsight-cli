"""core schema: incidents, run_records, review_queue, sessions

Revision ID: 7cad869057fa
Revises: 
Create Date: 2026-09-22 21:04:00.552394

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = '7cad869057fa'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "incidents",
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("establishment", sa.Text(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("normalized_fields", postgresql.JSONB(), nullable=False),
        sa.Column("narrative", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("outcome", postgresql.JSONB(), nullable=True),
        sa.Column("deciding_rule", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="submitted"),
    )

    op.create_table(
        "run_records",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("incidents.incident_id"), nullable=True),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("workers_dispatched", postgresql.JSONB(), nullable=True),
        sa.Column("tool_invocations", postgresql.JSONB(), nullable=True),
        sa.Column("rule_invocations", postgresql.JSONB(), nullable=True),
        sa.Column("escalation_triggers", postgresql.JSONB(), nullable=True),
        sa.Column("model_calls", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "review_queue",
        sa.Column("queue_id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("incidents.incident_id"), nullable=False),
        sa.Column("triggers", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("decision", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "sessions",
        sa.Column("thread_id", sa.Text(), primary_key=True),
        sa.Column("analyst_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("incidents.incident_id"), nullable=False),
        sa.Column("participant", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("sessions")
    op.drop_table("review_queue")
    op.drop_table("run_records")
    op.drop_table("incidents")