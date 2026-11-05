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
    bind = op.get_bind()
    # The original initial migration creates tables from live ORM metadata. On a fresh
    # database the new column may already exist; on an older database it must be added.
    if "source_block_id" not in _section_columns():
        if bind.dialect.name == "sqlite":
            # Alembic's SQLite add_column emits ADD COLUMN and then a separate
            # ADD CONSTRAINT, which SQLite does not support. Inline REFERENCES is
            # supported for a nullable column with an implicit NULL default.
            bind.exec_driver_sql(
                "ALTER TABLE sections ADD COLUMN source_block_id VARCHAR(36) "
                "REFERENCES source_blocks(id) ON DELETE RESTRICT"
            )
        else:
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
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite cannot drop a column that participates in a foreign key constraint
        # without rebuilding the self-referencing sections table. Keep the nullable
        # column/index as harmless forward-compatible schema residue rather than
        # risk losing section parent links or downstream references.
        return
    if "ix_sections_source_block_id" in _section_indexes():
        op.drop_index("ix_sections_source_block_id", table_name="sections")
    if "source_block_id" in _section_columns():
        op.drop_column("sections", "source_block_id")
