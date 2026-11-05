"""Link detected TOC sections to their heading evidence block."""

import sqlalchemy as sa
from alembic import op

revision = "0004_section_source_block"
down_revision = "0003_ocr_results"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite supports ADD COLUMN with a nullable REFERENCES column and NULL default.
    # Avoid batch table recreation: sections has a self-referencing parent_id FK, and
    # SQLite/Alembic can report a circular dependency while sorting that table's FKs.
    op.add_column(
        "sections",
        sa.Column(
            "source_block_id",
            sa.String(length=36),
            sa.ForeignKey("source_blocks.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_sections_source_block_id",
        "sections",
        ["source_block_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_sections_source_block_id", table_name="sections")
    op.drop_column("sections", "source_block_id")
