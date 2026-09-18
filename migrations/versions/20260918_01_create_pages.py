"""Create pages storage.

Revision ID: 20260918_01
Revises:
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260918_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "pages",
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("html", sa.Text(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("url"),
    )
    op.create_index(
        "pages_url_trgm_idx",
        "pages",
        ["url"],
        postgresql_ops={"url": "gin_trgm_ops"},
        postgresql_using="gin",
    )
    op.create_index(
        "pages_title_trgm_idx",
        "pages",
        ["title"],
        postgresql_ops={"title": "gin_trgm_ops"},
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("pages_title_trgm_idx", table_name="pages")
    op.drop_index("pages_url_trgm_idx", table_name="pages")
    op.drop_table("pages")
