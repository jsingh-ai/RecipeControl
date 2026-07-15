from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    DateTime as SQLDateTime,
)
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.type_api import TypeEngine

from recipecontrol.database import Base, utc_now


def DateTime(*, timezone: bool = False) -> TypeEngine[datetime]:
    return SQLDateTime(timezone=timezone).with_variant(MySQLDateTime(fsp=6), "mysql")


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class MachineModel(TimestampMixin, Base):
    __tablename__ = "rc_machine"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    source_key: Mapped[str] = mapped_column(String(255), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class RuleSetModel(TimestampMixin, Base):
    __tablename__ = "rc_rule_set"
    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("rc_machine.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    machine: Mapped[MachineModel] = relationship()
    versions: Mapped[list["RuleVersionModel"]] = relationship(
        back_populates="rule_set", cascade="all, delete-orphan"
    )
    __table_args__ = (UniqueConstraint("machine_id", "name", name="uq_rule_set_machine_name"),)


class RuleVersionModel(Base):
    __tablename__ = "rc_rule_version"
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_set_id: Mapped[int] = mapped_column(ForeignKey("rc_rule_set.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    root_operator: Mapped[str] = mapped_column(String(3), default="OR")
    status: Mapped[str] = mapped_column(String(10), default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rule_set: Mapped[RuleSetModel] = relationship(back_populates="versions")
    groups: Mapped[list["RuleGroupModel"]] = relationship(
        back_populates="version", cascade="all, delete-orphan", order_by="RuleGroupModel.position"
    )
    classifications: Mapped[list["ClassificationModel"]] = relationship(back_populates="version")
    __table_args__ = (
        UniqueConstraint("rule_set_id", "version_number", name="uq_rule_version_number"),
        CheckConstraint("root_operator IN ('AND','OR')", name="ck_rule_root_operator"),
        CheckConstraint("status IN ('DRAFT','LOCKED')", name="ck_rule_version_status"),
    )


class RuleGroupModel(Base):
    __tablename__ = "rc_rule_group"
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_version_id: Mapped[int] = mapped_column(ForeignKey("rc_rule_version.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    internal_operator: Mapped[str] = mapped_column(String(3))
    version: Mapped[RuleVersionModel] = relationship(back_populates="groups")
    conditions: Mapped[list["RuleConditionModel"]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
        order_by="RuleConditionModel.position",
    )
    __table_args__ = (
        UniqueConstraint("rule_version_id", "position", name="uq_rule_group_position"),
        CheckConstraint("internal_operator IN ('AND','OR')", name="ck_group_operator"),
    )


class RuleConditionModel(TimestampMixin, Base):
    __tablename__ = "rc_rule_condition"
    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("rc_rule_group.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    source_tag_key: Mapped[str] = mapped_column(String(255))
    source_display_name: Mapped[str] = mapped_column(String(255))
    source_raw_data_type: Mapped[str | None] = mapped_column(String(120))
    source_data_type: Mapped[str] = mapped_column(String(30))
    operator: Mapped[str] = mapped_column(String(30))
    minimum: Mapped[str | None] = mapped_column(String(100))
    maximum: Mapped[str | None] = mapped_column(String(100))
    comparison_value: Mapped[Any | None] = mapped_column(JSON)
    delta_amount: Mapped[str | None] = mapped_column(String(100))
    delta_window_minutes: Mapped[int | None] = mapped_column(Integer)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=0)
    group: Mapped[RuleGroupModel] = relationship(back_populates="conditions")
    __table_args__ = (
        UniqueConstraint("group_id", "position", name="uq_condition_position"),
        CheckConstraint("duration_minutes >= 0", name="ck_condition_duration"),
        CheckConstraint(
            "delta_window_minutes IS NULL OR delta_window_minutes >= 1",
            name="ck_condition_delta_window",
        ),
    )


class ClassificationModel(Base):
    __tablename__ = "rc_classification"
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_version_id: Mapped[int] = mapped_column(ForeignKey("rc_rule_version.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[RuleVersionModel] = relationship(back_populates="classifications")
    __table_args__ = (
        UniqueConstraint("rule_version_id", "name", name="uq_classification_version_name"),
    )


class AnalysisModel(Base):
    __tablename__ = "rc_analysis"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str | None] = mapped_column(String(200))
    machine_id: Mapped[int] = mapped_column(ForeignKey("rc_machine.id"), index=True)
    rule_version_id: Mapped[int] = mapped_column(ForeignKey("rc_rule_version.id"), index=True)
    selected_start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    selected_end_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_exclusive_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    mode: Mapped[str] = mapped_column(String(12), default="HISTORICAL")
    status: Mapped[str] = mapped_column(String(12), default="QUEUED")
    duplicate_of_analysis_id: Mapped[int | None] = mapped_column(ForeignKey("rc_analysis.id"))
    source_row_count: Mapped[int | None] = mapped_column(Integer)
    reproducibility_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    machine: Mapped[MachineModel] = relationship()
    rule_version: Mapped[RuleVersionModel] = relationship()
    __table_args__ = (
        CheckConstraint("mode IN ('HISTORICAL','LIVE')", name="ck_analysis_mode"),
        CheckConstraint(
            "status IN ('QUEUED','RUNNING','COMPLETE','FAILED','ACTIVE','STOPPED')",
            name="ck_analysis_status",
        ),
        Index(
            "ix_analysis_duplicate_lookup",
            "machine_id",
            "rule_version_id",
            "selected_start_utc",
            "selected_end_utc",
            "mode",
        ),
    )


class AnalysisJobModel(Base):
    __tablename__ = "rc_analysis_job"
    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("rc_analysis.id"), unique=True)
    state: Mapped[str] = mapped_column(String(12), default="QUEUED", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    claimed_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    persistence_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_details: Mapped[str | None] = mapped_column(Text)
    analysis: Mapped[AnalysisModel] = relationship()


class SegmentModel(Base):
    __tablename__ = "rc_segment"
    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("rc_analysis.id"), index=True)
    start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    system_state: Mapped[str] = mapped_column(String(30))
    contributing_condition_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    identity_key: Mapped[str] = mapped_column(String(255))
    quality_label: Mapped[str | None] = mapped_column(String(10))
    classification_id: Mapped[int | None] = mapped_column(ForeignKey("rc_classification.id"))
    classification_name_snapshot: Mapped[str | None] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(Text)
    active_live: Mapped[bool] = mapped_column(Boolean, default=False)
    label_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    classification: Mapped[ClassificationModel | None] = relationship()
    __table_args__ = (
        UniqueConstraint("analysis_id", "start_utc", name="uq_segment_analysis_start"),
        CheckConstraint(
            "system_state IN ('NORMAL','BREAK','DATA_GAP','INSUFFICIENT_HISTORY')",
            name="ck_segment_state",
        ),
        CheckConstraint(
            "quality_label IS NULL OR quality_label IN ('GOOD','BAD','UNSURE')",
            name="ck_quality_label",
        ),
    )

    @property
    def training_eligible(self) -> bool:
        return self.quality_label in {"GOOD", "BAD"} and self.system_state not in {
            "DATA_GAP",
            "INSUFFICIENT_HISTORY",
        }


class LabelHistoryModel(Base):
    __tablename__ = "rc_label_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("rc_segment.id"), index=True)
    quality_label: Mapped[str | None] = mapped_column(String(10))
    classification_id: Mapped[int | None] = mapped_column(Integer)
    classification_name_snapshot: Mapped[str | None] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ConditionIntervalModel(Base):
    __tablename__ = "rc_condition_interval"
    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("rc_analysis.id"), index=True)
    condition_id: Mapped[int] = mapped_column(ForeignKey("rc_rule_condition.id"), index=True)
    start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(30))
    trigger_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmation_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class AnalysisMinuteModel(Base):
    __tablename__ = "rc_analysis_minute"
    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("rc_analysis.id"), index=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("rc_segment.id"), index=True)
    minute_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    system_state: Mapped[str] = mapped_column(String(30))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    __table_args__ = (
        UniqueConstraint("analysis_id", "minute_utc", name="uq_analysis_minute"),
        Index("ix_analysis_minute_lookup", "analysis_id", "minute_utc"),
    )


class BoundaryEventModel(Base):
    __tablename__ = "rc_boundary_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("rc_analysis.id"), index=True)
    boundary_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    previous_identity: Mapped[str | None] = mapped_column(String(255))
    next_identity: Mapped[str] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(30))
    explanation: Mapped[str] = mapped_column(Text)
    context: Mapped[dict[str, Any]] = mapped_column(JSON)


class LiveSessionModel(Base):
    __tablename__ = "rc_live_session"
    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("rc_machine.id"), index=True)
    rule_version_id: Mapped[int] = mapped_column(ForeignKey("rc_rule_version.id"), index=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("rc_analysis.id"), unique=True)
    state: Mapped[str] = mapped_column(String(12), default="ACTIVE")
    finalization_lag_minutes: Mapped[int] = mapped_column(Integer, default=2)
    last_finalized_minute: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    analysis: Mapped[AnalysisModel] = relationship()


class ProcessingCheckpointModel(Base):
    __tablename__ = "rc_processing_checkpoint"
    id: Mapped[int] = mapped_column(primary_key=True)
    live_session_id: Mapped[int] = mapped_column(ForeignKey("rc_live_session.id"), index=True)
    checkpoint_key: Mapped[str] = mapped_column(String(100))
    checkpoint_value: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    __table_args__ = (
        UniqueConstraint("live_session_id", "checkpoint_key", name="uq_live_checkpoint"),
    )
