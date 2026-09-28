"""review queue snapshot and reviewer

Revision ID: d41e7a0c5b29
Revises: c93a06b2aade
Create Date: 2026-09-28 18:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd41e7a0c5b29'
down_revision: str | Sequence[str] | None = 'c93a06b2aade'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("review_queue", sa.Column("submitting_analyst_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("analysts.analyst_id"), nullable=True))
    op.add_column("review_queue", sa.Column("dossier_snapshot", postgresql.JSONB(), nullable=True))
    op.add_column("review_queue", sa.Column("citations", postgresql.JSONB(), nullable=True))
    op.add_column("review_queue", sa.Column("reviewer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("analysts.analyst_id"), nullable=True))
    op.add_column("review_queue", sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint("ck_review_queue_status", "review_queue", "status IN ('pending', 'approved', 'rejected')")
    op.create_check_constraint("ck_review_queue_separate_reviewer", "review_queue", "reviewer_id IS NULL OR reviewer_id <> submitting_analyst_id")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_review_queue_separate_reviewer", "review_queue", type_="check")
    op.drop_constraint("ck_review_queue_status", "review_queue", type_="check")
    op.drop_column("review_queue", "decided_at")
    op.drop_column("review_queue", "reviewer_id")
    op.drop_column("review_queue", "citations")
    op.drop_column("review_queue", "dossier_snapshot")
    op.drop_column("review_queue", "submitting_analyst_id")
