"""Link detected TOC sections to their heading evidence block."""

import sqlalchemy as sa
from alembic import op

revision = "0004_section_source_block"
down_revision = "0003_ocr_results"
branch_labels = None
depends_on = None


def _section_columns() -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("sections")
    }


def _section_indexes() -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes("sections")
    }


def upgrade() -> None:
    # The original initial migration creates tables from live ORM metadata. On a fresh
    # database the new column may already exist; on an older database it must be added.
    if "source_block_id" not in _section_columns():
        op.add_column(
            "sections",
            sa.Column(
                "source_block_id",
                sa.String(length=36),
                sa.ForeignKey("source_blocks.id", ondelete="RESTRICT"),
                nullable=True,
            ),
        )

    if "ix_sections_source_block_id" not in _section_indexes():
        op.create_index(
            "ix_sections_source_block_id",
            "sections",
            ["source_block_id"],
            unique=False,
        )


def downgrade() -> None:
    if "ix_sections_source_block_id" in _section_indexes():
        op.drop_index("ix_sections_source_block_id", table_name="sections")
    if "source_block_id" in _section_columns():
        op.drop_column("sections", "source_block_id")
