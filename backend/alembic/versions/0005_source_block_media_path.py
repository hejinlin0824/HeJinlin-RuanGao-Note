"""Keep MinerU media paths on page-linked source evidence blocks."""

import sqlalchemy as sa
from alembic import op

revision = "0005_source_block_media_path"
down_revision = "0004_section_source_block"
branch_labels = None
depends_on = None


def _source_block_columns() -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("source_blocks")
    }


def upgrade() -> None:
    # 0001 builds new databases from current ORM metadata, so the column may
    # already exist on a fresh install. Existing installations need the additive DDL.
    if "media_path" not in _source_block_columns():
        op.add_column(
            "source_blocks",
            sa.Column("media_path", sa.String(length=1000), nullable=True),
        )


def downgrade() -> None:
    if "media_path" in _source_block_columns():
        op.drop_column("source_blocks", "media_path")
