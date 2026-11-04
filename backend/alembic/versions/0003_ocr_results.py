"""Persist normalized OCR output and image quality diagnostics."""

from alembic import op
import sqlalchemy as sa

revision = "0003_ocr_results"
down_revision = "0002_page_replacement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("processing_runs")}
    if "normalized_result" not in existing:
        op.add_column("processing_runs", sa.Column("normalized_result", sa.JSON(), nullable=True))
    if "quality_report" not in existing:
        op.add_column("processing_runs", sa.Column("quality_report", sa.JSON(), nullable=True))


def downgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("processing_runs")}
    with op.batch_alter_table("processing_runs") as batch_op:
        if "quality_report" in existing:
            batch_op.drop_column("quality_report")
        if "normalized_result" in existing:
            batch_op.drop_column("normalized_result")
