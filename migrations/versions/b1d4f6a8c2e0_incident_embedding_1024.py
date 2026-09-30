"""incident narrative embeddings are 1024 dimensions, the size Titan Text Embeddings v2 is configured for

Titan v2 produces 256, 512 or 1024 dimensions, never 1536, so no embedding could fit the old column. A vector
can't be cast to another size, so existing values are cleared; they're derived from the narrative and rebuilt.

Revision ID: b1d4f6a8c2e0
Revises: a7c3e9d1f2b4
Create Date: 2026-09-30 13:00:00.000000

"""
from collections.abc import Sequence

from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = 'b1d4f6a8c2e0'
down_revision: str | Sequence[str] | None = 'a7c3e9d1f2b4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("incidents", "embedding", type_=Vector(1024), postgresql_using="NULL")


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column("incidents", "embedding", type_=Vector(1536), postgresql_using="NULL")
