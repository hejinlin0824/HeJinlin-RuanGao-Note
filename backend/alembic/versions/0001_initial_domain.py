"""Create the initial textbook and learning domain schema.

This bootstrap migration creates the schema from the versioned SQLAlchemy
metadata. Subsequent revisions must use explicit Alembic operations so that
historical migrations remain immutable.
"""

from alembic import op

from ruangao_note.db.base import Base
from ruangao_note.domain import models as _models  # noqa: F401

revision = "0001_initial_domain"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create all initial domain tables and indexes."""
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """Drop the initial domain tables."""
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
