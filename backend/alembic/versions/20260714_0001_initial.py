"""Create all RecipeControl application tables.

Revision ID: 20260714_0001
Revises:
"""

from alembic import op
from recipecontrol import models  # noqa: F401
from recipecontrol.database import Base

revision = "20260714_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=False)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=True)
