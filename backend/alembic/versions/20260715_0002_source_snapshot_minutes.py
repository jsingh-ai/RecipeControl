"""Add raw source type snapshots and exact-minute evaluations.

Revision ID: 20260715_0002
Revises: 20260714_0001
"""

import sqlalchemy as sa

from alembic import op

revision = "20260715_0002"
down_revision = "20260714_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rc_rule_condition", sa.Column("source_raw_data_type", sa.String(120), nullable=True)
    )
    op.create_table(
        "rc_analysis_minute",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("analysis_id", sa.Integer(), sa.ForeignKey("rc_analysis.id"), nullable=False),
        sa.Column("segment_id", sa.Integer(), sa.ForeignKey("rc_segment.id"), nullable=False),
        sa.Column("minute_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_state", sa.String(30), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.UniqueConstraint("analysis_id", "minute_utc", name="uq_analysis_minute"),
    )
    op.create_index("ix_rc_analysis_minute_analysis_id", "rc_analysis_minute", ["analysis_id"])
    op.create_index("ix_rc_analysis_minute_segment_id", "rc_analysis_minute", ["segment_id"])
    op.create_index(
        "ix_analysis_minute_lookup", "rc_analysis_minute", ["analysis_id", "minute_utc"]
    )


def downgrade() -> None:
    op.drop_table("rc_analysis_minute")
    op.drop_column("rc_rule_condition", "source_raw_data_type")
