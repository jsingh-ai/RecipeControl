from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MachineOut(ORMModel):
    id: int
    source_key: str
    name: str
    enabled: bool


class TagOut(BaseModel):
    key: str
    display_name: str
    raw_data_type: str | None
    data_kind: Literal["numeric", "text", "boolean"]
    units: str | None = None
    node_id: str | None = None
    opc_path: str | None = None


class ConditionWrite(BaseModel):
    id: int | None = None
    tag_id: str | None = None
    # Accepted only for compatibility with older drafts. Authoritative metadata is
    # always reloaded from the source before persistence.
    source_tag_key: str | None = None
    source_display_name: str | None = None
    source_raw_data_type: str | None = None
    source_data_type: Literal["numeric", "text", "boolean"] | None = None
    operator: Literal[
        "BELOW_MINIMUM",
        "ABOVE_MAXIMUM",
        "OUTSIDE_RANGE",
        "EQUALS",
        "NOT_EQUALS",
        "INCREASE_BY",
        "DECREASE_BY",
    ]
    minimum: str | None = None
    maximum: str | None = None
    comparison_value: Any | None = None
    delta_amount: str | None = None
    delta_window_minutes: int | None = Field(default=None, ge=1)
    duration_minutes: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def selected_tag(self) -> "ConditionWrite":
        selected = self.tag_id or self.source_tag_key
        if not selected:
            raise ValueError("Choose a source tag")
        self.tag_id = selected
        return self


class GroupWrite(BaseModel):
    internal_operator: Literal["AND", "OR"]
    conditions: list[ConditionWrite]


class DraftWrite(BaseModel):
    root_operator: Literal["AND", "OR"] = "OR"
    groups: list[GroupWrite]


class RuleSetCreate(BaseModel):
    machine_id: int
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Rule-set name cannot be blank")
        return stripped


class ClassificationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Classification name cannot be blank")
        return stripped


class AnalysisCreate(BaseModel):
    machine_id: int
    rule_version_id: int
    selected_start_utc: datetime
    selected_end_utc: datetime
    title: str | None = Field(default=None, max_length=200)
    create_duplicate: bool = False

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("Analysis title cannot be blank")
        return stripped

    @field_validator("selected_start_utc", "selected_end_utc")
    @classmethod
    def utc_minute(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must include UTC timezone")
        result = value.astimezone(UTC)
        if result.second or result.microsecond:
            raise ValueError("timestamp must have minute precision")
        return result

    @model_validator(mode="after")
    def ordered(self) -> "AnalysisCreate":
        if self.selected_start_utc > self.selected_end_utc:
            raise ValueError("start must not be after end")
        return self

    @property
    def end_exclusive(self) -> datetime:
        return self.selected_end_utc + timedelta(minutes=1)


class SegmentLabelUpdate(BaseModel):
    quality_label: Literal["GOOD", "BAD", "UNSURE"] | None = None
    classification_id: int | None = None
    note: str | None = None


class LiveCreate(BaseModel):
    machine_id: int
    rule_version_id: int
    finalization_lag_minutes: int = Field(default=2, ge=0, le=60)
