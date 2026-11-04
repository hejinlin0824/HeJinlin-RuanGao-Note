"""Track which immutable page record supersedes an earlier page."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0002_page_replacement"
down_revision = "0001_initial_domain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the replacement lineage column for databases created before TP-03."""
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("chapter_pages")}
    if "replaces_page_id" not in columns:
        op.add_column(
            "chapter_pages",
            sa.Column(
                "replaces_page_id",
                sa.String(length=36),
                sa.ForeignKey("chapter_pages.id", ondelete="RESTRICT"),
                nullable=True,
            ),
        )


def downgrade() -> None:
    """Remove replacement lineage when rolling back TP-03."""
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("chapter_pages")}
    if "replaces_page_id" in columns:
        with op.batch_alter_table("chapter_pages") as batch_op:
            batch_op.drop_column("replaces_page_id")
