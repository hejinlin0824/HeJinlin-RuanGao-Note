"""Link detected TOC sections to their heading evidence block."""

import sqlalchemy as sa
from alembic import op

revision = "0004_section_source_block"
down_revision = "0003_ocr_results"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sections") as batch_op:
        batch_op.add_column(sa.Column("source_block_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_sections_source_block_id_source_blocks",
            "source_blocks",
            ["source_block_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index(
            "ix_sections_source_block_id",
            ["source_block_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("sections") as batch_op:
        batch_op.drop_index("ix_sections_source_block_id")
        batch_op.drop_constraint(
            "fk_sections_source_block_id_source_blocks",
            type_="foreignkey",
        )
        batch_op.drop_column("source_block_id")
