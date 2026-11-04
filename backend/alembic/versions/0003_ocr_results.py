"""Persist normalized OCR output and image quality diagnostics."""

from alembic import op
import sqlalchemy as sa

revision = "0003_ocr_results"
down_revision = "0002_page_replacement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("processing_runs", sa.Column("normalized_result", sa.JSON(), nullable=True))
    op.add_column("processing_runs", sa.Column("quality_report", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("processing_runs") as batch_op:
        batch_op.drop_column("quality_report")
        batch_op.drop_column("normalized_result")
