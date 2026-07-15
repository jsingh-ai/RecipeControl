"""Use microsecond precision for RecipeControl UTC datetimes on MySQL.

Revision ID: 20260715_0003
Revises: 20260715_0002
"""

from collections.abc import Iterable

from sqlalchemy.dialects import mysql

from alembic import op

revision = "20260715_0003"
down_revision = "20260715_0002"
branch_labels = None
depends_on = None


DATETIME_COLUMNS: tuple[tuple[str, str, bool], ...] = (
    ("rc_machine", "created_at", False),
    ("rc_machine", "updated_at", False),
    ("rc_rule_set", "created_at", False),
    ("rc_rule_set", "updated_at", False),
    ("rc_rule_version", "created_at", False),
    ("rc_rule_version", "locked_at", True),
    ("rc_classification", "created_at", False),
    ("rc_classification", "retired_at", True),
    ("rc_analysis", "selected_start_utc", False),
    ("rc_analysis", "selected_end_utc", False),
    ("rc_analysis", "end_exclusive_utc", False),
    ("rc_analysis", "created_at", False),
    ("rc_analysis", "started_at", True),
    ("rc_analysis", "completed_at", True),
    ("rc_analysis_job", "created_at", False),
    ("rc_analysis_job", "claimed_at", True),
    ("rc_analysis_job", "heartbeat_at", True),
    ("rc_analysis_job", "finished_at", True),
    ("rc_segment", "start_utc", False),
    ("rc_segment", "end_utc", False),
    ("rc_segment", "label_updated_at", True),
    ("rc_label_history", "changed_at", False),
    ("rc_condition_interval", "start_utc", False),
    ("rc_condition_interval", "end_utc", False),
    ("rc_condition_interval", "trigger_utc", True),
    ("rc_condition_interval", "confirmation_utc", True),
    ("rc_boundary_event", "boundary_utc", False),
    ("rc_live_session", "last_finalized_minute", True),
    ("rc_live_session", "worker_heartbeat_at", True),
    ("rc_live_session", "created_at", False),
    ("rc_live_session", "stopped_at", True),
    ("rc_processing_checkpoint", "updated_at", False),
    ("rc_analysis_minute", "minute_utc", False),
)


def _alter(columns: Iterable[tuple[str, str, bool]], *, precision: int | None) -> None:
    if op.get_bind().dialect.name != "mysql":
        return
    target = mysql.DATETIME(fsp=precision)
    for table_name, column_name, nullable in columns:
        op.alter_column(
            table_name,
            column_name,
            existing_type=mysql.DATETIME(),
            type_=target,
            existing_nullable=nullable,
        )


def upgrade() -> None:
    _alter(DATETIME_COLUMNS, precision=6)


def downgrade() -> None:
    _alter(reversed(DATETIME_COLUMNS), precision=None)
