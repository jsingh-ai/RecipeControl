"""Add a bounded lease for atomic historical persistence.

Revision ID: 20260715_0004
Revises: 20260715_0003
"""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20260715_0004"
down_revision = "20260715_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rc_analysis_job",
        sa.Column(
            "persistence_lease_until",
            sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("rc_analysis_job", "persistence_lease_until")
