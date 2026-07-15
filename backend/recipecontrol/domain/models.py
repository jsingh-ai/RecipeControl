from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class DataType(StrEnum):
    NUMERIC = "numeric"
    TEXT = "text"
    BOOLEAN = "boolean"


class ConditionOperator(StrEnum):
    BELOW_MINIMUM = "BELOW_MINIMUM"
    ABOVE_MAXIMUM = "ABOVE_MAXIMUM"
    OUTSIDE_RANGE = "OUTSIDE_RANGE"
    EQUALS = "EQUALS"
    NOT_EQUALS = "NOT_EQUALS"
    INCREASE_BY = "INCREASE_BY"
    DECREASE_BY = "DECREASE_BY"


class LogicOperator(StrEnum):
    AND = "AND"
    OR = "OR"


class SystemState(StrEnum):
    NORMAL = "NORMAL"
    BREAK = "BREAK"
    DATA_GAP = "DATA_GAP"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"


class LaneState(StrEnum):
    FALSE = "FALSE"
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    MISSING = "MISSING"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"


Scalar = Decimal | str | bool


@dataclass(frozen=True, slots=True)
class Condition:
    id: int
    tag_key: str
    display_name: str
    data_type: DataType
    operator: ConditionOperator
    duration_minutes: int = 0
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    comparison_value: Scalar | None = None
    delta_amount: Decimal | None = None
    delta_window_minutes: int | None = None

    @property
    def is_delta(self) -> bool:
        return self.operator in {
            ConditionOperator.INCREASE_BY,
            ConditionOperator.DECREASE_BY,
        }


@dataclass(frozen=True, slots=True)
class Group:
    id: int
    operator: LogicOperator
    conditions: tuple[Condition, ...]


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    root_operator: LogicOperator
    groups: tuple[Group, ...]

    @property
    def conditions(self) -> tuple[Condition, ...]:
        return tuple(condition for group in self.groups for condition in group.conditions)

    @property
    def preload_minutes(self) -> int:
        return max(
            (
                condition.duration_minutes + (condition.delta_window_minutes or 0) + 1
                for condition in self.conditions
            ),
            default=1,
        )


@dataclass(frozen=True, slots=True)
class Segment:
    start_utc: datetime
    end_utc: datetime
    system_state: SystemState
    identity: str
    contributing_condition_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class ConditionInterval:
    condition_id: int
    start_utc: datetime
    end_utc: datetime
    state: LaneState
    trigger_utc: datetime | None = None
    confirmation_utc: datetime | None = None


@dataclass(frozen=True, slots=True)
class BoundaryEvent:
    boundary_utc: datetime
    previous_identity: str | None
    next_identity: str
    system_state: SystemState
    contributing_condition_ids: tuple[int, ...]
    explanation: str
    context: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SegmentationResult:
    start_utc: datetime
    end_utc: datetime
    source_row_count: int
    segments: tuple[Segment, ...]
    condition_intervals: tuple[ConditionInterval, ...]
    boundaries: tuple[BoundaryEvent, ...]
