"""Create RecipeControl application tables with explicit operations.

Revision ID: 20260714_0001
Revises:
"""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.sql.type_api import TypeEngine

from alembic import op

revision = "20260714_0001"
down_revision = None
branch_labels = None
depends_on = None


def _utc_datetime() -> TypeEngine[object]:
    return sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql")


def _timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.Column("updated_at", _utc_datetime(), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "rc_machine",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("source_key", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("source_key"),
    )
    op.create_table(
        "rc_rule_set",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("machine_id", sa.Integer(), sa.ForeignKey("rc_machine.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("machine_id", "name", name="uq_rule_set_machine_name"),
    )
    op.create_index("ix_rc_rule_set_machine_id", "rc_rule_set", ["machine_id"])
    op.create_table(
        "rc_rule_version",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_set_id", sa.Integer(), sa.ForeignKey("rc_rule_set.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("root_operator", sa.String(3), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.Column("locked_at", _utc_datetime()),
        sa.CheckConstraint("root_operator IN ('AND','OR')", name="ck_rule_root_operator"),
        sa.CheckConstraint("status IN ('DRAFT','LOCKED')", name="ck_rule_version_status"),
        sa.UniqueConstraint("rule_set_id", "version_number", name="uq_rule_version_number"),
    )
    op.create_index("ix_rc_rule_version_rule_set_id", "rc_rule_version", ["rule_set_id"])
    op.create_table(
        "rc_rule_group",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "rule_version_id", sa.Integer(), sa.ForeignKey("rc_rule_version.id"), nullable=False
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("internal_operator", sa.String(3), nullable=False),
        sa.CheckConstraint("internal_operator IN ('AND','OR')", name="ck_group_operator"),
        sa.UniqueConstraint("rule_version_id", "position", name="uq_rule_group_position"),
    )
    op.create_index("ix_rc_rule_group_rule_version_id", "rc_rule_group", ["rule_version_id"])
    op.create_table(
        "rc_rule_condition",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("rc_rule_group.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("source_tag_key", sa.String(255), nullable=False),
        sa.Column("source_display_name", sa.String(255), nullable=False),
        sa.Column("source_data_type", sa.String(30), nullable=False),
        sa.Column("operator", sa.String(30), nullable=False),
        sa.Column("minimum", sa.String(100)),
        sa.Column("maximum", sa.String(100)),
        sa.Column("comparison_value", sa.JSON()),
        sa.Column("delta_amount", sa.String(100)),
        sa.Column("delta_window_minutes", sa.Integer()),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("duration_minutes >= 0", name="ck_condition_duration"),
        sa.CheckConstraint(
            "delta_window_minutes IS NULL OR delta_window_minutes >= 1",
            name="ck_condition_delta_window",
        ),
        sa.UniqueConstraint("group_id", "position", name="uq_condition_position"),
    )
    op.create_index("ix_rc_rule_condition_group_id", "rc_rule_condition", ["group_id"])
    op.create_table(
        "rc_classification",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "rule_version_id", sa.Integer(), sa.ForeignKey("rc_rule_version.id"), nullable=False
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.Column("retired_at", _utc_datetime()),
        sa.UniqueConstraint("rule_version_id", "name", name="uq_classification_version_name"),
    )
    op.create_index(
        "ix_rc_classification_rule_version_id", "rc_classification", ["rule_version_id"]
    )
    op.create_table(
        "rc_analysis",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(200)),
        sa.Column("machine_id", sa.Integer(), sa.ForeignKey("rc_machine.id"), nullable=False),
        sa.Column(
            "rule_version_id", sa.Integer(), sa.ForeignKey("rc_rule_version.id"), nullable=False
        ),
        sa.Column("selected_start_utc", _utc_datetime(), nullable=False),
        sa.Column("selected_end_utc", _utc_datetime(), nullable=False),
        sa.Column("end_exclusive_utc", _utc_datetime(), nullable=False),
        sa.Column("mode", sa.String(12), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("duplicate_of_analysis_id", sa.Integer(), sa.ForeignKey("rc_analysis.id")),
        sa.Column("source_row_count", sa.Integer()),
        sa.Column("reproducibility_metadata", sa.JSON()),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.Column("started_at", _utc_datetime()),
        sa.Column("completed_at", _utc_datetime()),
        sa.CheckConstraint("mode IN ('HISTORICAL','LIVE')", name="ck_analysis_mode"),
        sa.CheckConstraint(
            "status IN ('QUEUED','RUNNING','COMPLETE','FAILED','ACTIVE','STOPPED')",
            name="ck_analysis_status",
        ),
    )
    op.create_index("ix_rc_analysis_machine_id", "rc_analysis", ["machine_id"])
    op.create_index("ix_rc_analysis_rule_version_id", "rc_analysis", ["rule_version_id"])
    op.create_index(
        "ix_analysis_duplicate_lookup",
        "rc_analysis",
        ["machine_id", "rule_version_id", "selected_start_utc", "selected_end_utc", "mode"],
    )
    op.create_table(
        "rc_analysis_job",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "analysis_id",
            sa.Integer(),
            sa.ForeignKey("rc_analysis.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("state", sa.String(12), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("claimed_by", sa.String(100)),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.Column("claimed_at", _utc_datetime()),
        sa.Column("heartbeat_at", _utc_datetime()),
        sa.Column("finished_at", _utc_datetime()),
        sa.Column("error_details", sa.Text()),
    )
    op.create_index("ix_rc_analysis_job_state", "rc_analysis_job", ["state"])
    op.create_table(
        "rc_segment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("analysis_id", sa.Integer(), sa.ForeignKey("rc_analysis.id"), nullable=False),
        sa.Column("start_utc", _utc_datetime(), nullable=False),
        sa.Column("end_utc", _utc_datetime(), nullable=False),
        sa.Column("system_state", sa.String(30), nullable=False),
        sa.Column("contributing_condition_ids", sa.JSON(), nullable=False),
        sa.Column("identity_key", sa.String(255), nullable=False),
        sa.Column("quality_label", sa.String(10)),
        sa.Column("classification_id", sa.Integer(), sa.ForeignKey("rc_classification.id")),
        sa.Column("classification_name_snapshot", sa.String(200)),
        sa.Column("note", sa.Text()),
        sa.Column("active_live", sa.Boolean(), nullable=False),
        sa.Column("label_updated_at", _utc_datetime()),
        sa.CheckConstraint(
            "system_state IN ('NORMAL','BREAK','DATA_GAP','INSUFFICIENT_HISTORY')",
            name="ck_segment_state",
        ),
        sa.CheckConstraint(
            "quality_label IS NULL OR quality_label IN ('GOOD','BAD','UNSURE')",
            name="ck_quality_label",
        ),
        sa.UniqueConstraint("analysis_id", "start_utc", name="uq_segment_analysis_start"),
    )
    op.create_index("ix_rc_segment_analysis_id", "rc_segment", ["analysis_id"])
    op.create_table(
        "rc_label_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("segment_id", sa.Integer(), sa.ForeignKey("rc_segment.id"), nullable=False),
        sa.Column("quality_label", sa.String(10)),
        sa.Column("classification_id", sa.Integer()),
        sa.Column("classification_name_snapshot", sa.String(200)),
        sa.Column("note", sa.Text()),
        sa.Column("changed_at", _utc_datetime(), nullable=False),
    )
    op.create_index("ix_rc_label_history_segment_id", "rc_label_history", ["segment_id"])
    op.create_table(
        "rc_condition_interval",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("analysis_id", sa.Integer(), sa.ForeignKey("rc_analysis.id"), nullable=False),
        sa.Column(
            "condition_id", sa.Integer(), sa.ForeignKey("rc_rule_condition.id"), nullable=False
        ),
        sa.Column("start_utc", _utc_datetime(), nullable=False),
        sa.Column("end_utc", _utc_datetime(), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("trigger_utc", _utc_datetime()),
        sa.Column("confirmation_utc", _utc_datetime()),
        sa.Column("summary_metadata", sa.JSON()),
    )
    op.create_index(
        "ix_rc_condition_interval_analysis_id", "rc_condition_interval", ["analysis_id"]
    )
    op.create_index(
        "ix_rc_condition_interval_condition_id", "rc_condition_interval", ["condition_id"]
    )
    op.create_table(
        "rc_boundary_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("analysis_id", sa.Integer(), sa.ForeignKey("rc_analysis.id"), nullable=False),
        sa.Column("boundary_utc", _utc_datetime(), nullable=False),
        sa.Column("previous_identity", sa.String(255)),
        sa.Column("next_identity", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
    )
    op.create_index("ix_rc_boundary_event_analysis_id", "rc_boundary_event", ["analysis_id"])
    op.create_table(
        "rc_live_session",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("machine_id", sa.Integer(), sa.ForeignKey("rc_machine.id"), nullable=False),
        sa.Column(
            "rule_version_id", sa.Integer(), sa.ForeignKey("rc_rule_version.id"), nullable=False
        ),
        sa.Column(
            "analysis_id",
            sa.Integer(),
            sa.ForeignKey("rc_analysis.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("state", sa.String(12), nullable=False),
        sa.Column("finalization_lag_minutes", sa.Integer(), nullable=False),
        sa.Column("last_finalized_minute", _utc_datetime()),
        sa.Column("worker_heartbeat_at", _utc_datetime()),
        sa.Column("created_at", _utc_datetime(), nullable=False),
        sa.Column("stopped_at", _utc_datetime()),
    )
    op.create_index("ix_rc_live_session_machine_id", "rc_live_session", ["machine_id"])
    op.create_index("ix_rc_live_session_rule_version_id", "rc_live_session", ["rule_version_id"])
    op.create_table(
        "rc_processing_checkpoint",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "live_session_id", sa.Integer(), sa.ForeignKey("rc_live_session.id"), nullable=False
        ),
        sa.Column("checkpoint_key", sa.String(100), nullable=False),
        sa.Column("checkpoint_value", sa.JSON(), nullable=False),
        sa.Column("updated_at", _utc_datetime(), nullable=False),
        sa.UniqueConstraint("live_session_id", "checkpoint_key", name="uq_live_checkpoint"),
    )
    op.create_index(
        "ix_rc_processing_checkpoint_live_session_id",
        "rc_processing_checkpoint",
        ["live_session_id"],
    )


def downgrade() -> None:
    for table in (
        "rc_processing_checkpoint",
        "rc_live_session",
        "rc_boundary_event",
        "rc_condition_interval",
        "rc_label_history",
        "rc_segment",
        "rc_analysis_job",
        "rc_analysis",
        "rc_classification",
        "rc_rule_condition",
        "rc_rule_group",
        "rc_rule_version",
        "rc_rule_set",
        "rc_machine",
    ):
        op.drop_table(table)
