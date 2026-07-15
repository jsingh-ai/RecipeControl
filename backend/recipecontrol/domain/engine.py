from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from recipecontrol.domain.models import (
    BoundaryEvent,
    Condition,
    ConditionInterval,
    ConditionOperator,
    DataType,
    LaneState,
    LogicOperator,
    RuleDefinition,
    Segment,
    SegmentationResult,
    SystemState,
)
from recipecontrol.source.base import Sample

MINUTE = timedelta(minutes=1)


class RuleEvaluationError(ValueError):
    pass


def _utc_minute(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise RuleEvaluationError(f"{name} must be timezone-aware UTC")
    value = value.astimezone(UTC)
    if value.second or value.microsecond:
        raise RuleEvaluationError(f"{name} must have minute precision")
    return value


def _minutes(start: datetime, end: datetime) -> list[datetime]:
    count = int((end - start) / MINUTE)
    return [start + index * MINUTE for index in range(count)]


def _tie_rank(value: int | str) -> tuple[int, int | str]:
    return (0, value) if isinstance(value, int) else (1, str(value))


def _normalize(value: object, data_type: DataType) -> Decimal | str | bool:
    if data_type is DataType.NUMERIC:
        if isinstance(value, bool):
            raise RuleEvaluationError("Boolean source value cannot be used as numeric")
        try:
            return Decimal(str(value))
        except InvalidOperation as error:
            raise RuleEvaluationError(f"Invalid numeric source value: {value!r}") from error
    if data_type is DataType.BOOLEAN:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, Decimal)) and value in (0, 1):
            return bool(value)
        normalized = str(value).strip().casefold()
        if normalized in {"true", "1"}:
            return True
        if normalized in {"false", "0"}:
            return False
        raise RuleEvaluationError(f"Invalid Boolean source value: {value!r}")
    return str(value)


def _validate_rule(rule: RuleDefinition) -> None:
    if not rule.groups or not rule.conditions:
        raise RuleEvaluationError("A rule requires at least one group and condition")
    seen: set[int] = set()
    for group in rule.groups:
        if not group.conditions:
            raise RuleEvaluationError("Saved groups cannot be empty")
        for condition in group.conditions:
            if condition.id in seen:
                raise RuleEvaluationError("Condition IDs must be unique")
            seen.add(condition.id)
            if condition.duration_minutes < 0:
                raise RuleEvaluationError("Duration cannot be negative")
            numeric_only = {
                ConditionOperator.BELOW_MINIMUM,
                ConditionOperator.ABOVE_MAXIMUM,
                ConditionOperator.OUTSIDE_RANGE,
                ConditionOperator.INCREASE_BY,
                ConditionOperator.DECREASE_BY,
            }
            if condition.operator in numeric_only and condition.data_type is not DataType.NUMERIC:
                raise RuleEvaluationError("Selected operator requires a numeric condition")
            if condition.operator is ConditionOperator.BELOW_MINIMUM and condition.minimum is None:
                raise RuleEvaluationError("Below minimum requires minimum")
            if condition.operator is ConditionOperator.ABOVE_MAXIMUM and condition.maximum is None:
                raise RuleEvaluationError("Above maximum requires maximum")
            if condition.operator is ConditionOperator.OUTSIDE_RANGE:
                if condition.minimum is None or condition.maximum is None:
                    raise RuleEvaluationError("Outside range requires both bounds")
                if condition.minimum > condition.maximum:
                    raise RuleEvaluationError("Minimum cannot exceed maximum")
            if (
                condition.operator in {ConditionOperator.EQUALS, ConditionOperator.NOT_EQUALS}
                and condition.comparison_value is None
            ):
                raise RuleEvaluationError("Equality requires a comparison value")
            if condition.is_delta:
                if condition.delta_amount is None or condition.delta_amount <= 0:
                    raise RuleEvaluationError("Delta amount must be positive")
                if not condition.delta_window_minutes or condition.delta_window_minutes < 1:
                    raise RuleEvaluationError("Delta window must be at least one minute")


def validate_rule(rule: RuleDefinition) -> None:
    """Validate a rule without source access or evaluation side effects."""
    _validate_rule(rule)


def _raw_predicate(
    condition: Condition,
    current: Decimal | str | bool,
    reference: Decimal | str | bool | None,
) -> bool:
    operator = condition.operator
    if operator is ConditionOperator.BELOW_MINIMUM:
        return current < condition.minimum  # type: ignore[operator]
    if operator is ConditionOperator.ABOVE_MAXIMUM:
        return current > condition.maximum  # type: ignore[operator]
    if operator is ConditionOperator.OUTSIDE_RANGE:
        return current < condition.minimum or current > condition.maximum  # type: ignore[operator]
    if operator is ConditionOperator.EQUALS:
        return current == condition.comparison_value
    if operator is ConditionOperator.NOT_EQUALS:
        return current != condition.comparison_value
    if not isinstance(current, Decimal) or not isinstance(reference, Decimal):
        raise RuleEvaluationError("Delta values must be numeric")
    if operator is ConditionOperator.INCREASE_BY:
        return current - reference >= condition.delta_amount  # type: ignore[operator]
    if operator is ConditionOperator.DECREASE_BY:
        return reference - current >= condition.delta_amount  # type: ignore[operator]
    raise RuleEvaluationError(f"Unsupported operator: {operator}")


def _duration_states(
    condition: Condition,
    raw: list[bool | None],
    system: list[SystemState | None],
    grid: list[datetime],
) -> tuple[list[LaneState], list[datetime | None], list[datetime | None]]:
    states = [LaneState.FALSE for _ in raw]
    triggers: list[datetime | None] = [None for _ in raw]
    confirmations: list[datetime | None] = [None for _ in raw]
    index = 0
    required = max(1, condition.duration_minutes)
    while index < len(raw):
        if system[index] is SystemState.DATA_GAP:
            states[index] = LaneState.MISSING
            index += 1
            continue
        if system[index] is SystemState.INSUFFICIENT_HISTORY:
            states[index] = LaneState.INSUFFICIENT_HISTORY
            index += 1
            continue
        if raw[index] is not True:
            index += 1
            continue
        run_start = index
        while index < len(raw) and raw[index] is True:
            index += 1
        run_end = index
        confirmed = run_end - run_start >= required
        trigger = grid[run_start]
        confirmation = grid[run_start + required - 1] if confirmed else None
        for run_index in range(run_start, run_end):
            states[run_index] = LaneState.ACTIVE if confirmed else LaneState.PENDING
            triggers[run_index] = trigger
            confirmations[run_index] = confirmation
    return states, triggers, confirmations


def _logic(operator: LogicOperator, values: list[bool]) -> bool:
    return all(values) if operator is LogicOperator.AND else any(values)


def _json_value(value: object | None) -> object | None:
    return str(value) if isinstance(value, Decimal) else value


def segment_timeline(
    rule: RuleDefinition,
    samples: Iterable[Sample],
    selected_start_utc: datetime,
    selected_end_minute_utc: datetime,
) -> SegmentationResult:
    """Generate deterministic half-open output from an inclusive selected end minute."""
    _validate_rule(rule)
    start = _utc_minute(selected_start_utc, "selected_start_utc")
    inclusive_end = _utc_minute(selected_end_minute_utc, "selected_end_minute_utc")
    if start > inclusive_end:
        raise RuleEvaluationError("Start must not be after end")
    end = inclusive_end + MINUTE
    preload_start = start - rule.preload_minutes * MINUTE
    grid = _minutes(preload_start, end)
    grid_index = {minute: index for index, minute in enumerate(grid)}
    conditions = rule.conditions
    tag_types: dict[str, DataType] = {}
    for condition in conditions:
        existing = tag_types.setdefault(condition.tag_key, condition.data_type)
        if existing is not condition.data_type:
            raise RuleEvaluationError("One source tag cannot have conflicting data type snapshots")

    chosen: dict[tuple[str, datetime], Sample] = {}
    source_row_count = 0
    for sample in samples:
        source_row_count += 1
        if sample.tag_key not in tag_types:
            continue
        stamp = sample.sampled_at_utc
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        stamp = stamp.astimezone(UTC)
        minute = stamp.replace(second=0, microsecond=0)
        if minute < preload_start or minute >= end:
            continue
        key = (sample.tag_key, minute)
        incumbent = chosen.get(key)
        candidate_rank = (stamp, _tie_rank(sample.tie_breaker))
        if incumbent is None:
            chosen[key] = Sample(sample.tag_key, stamp, sample.value, sample.tie_breaker)
        else:
            old_stamp = incumbent.sampled_at_utc
            if old_stamp.tzinfo is None:
                old_stamp = old_stamp.replace(tzinfo=UTC)
            if candidate_rank > (old_stamp.astimezone(UTC), _tie_rank(incumbent.tie_breaker)):
                chosen[key] = Sample(sample.tag_key, stamp, sample.value, sample.tie_breaker)

    values: dict[str, list[Decimal | str | bool | None]] = {
        tag_key: [None for _ in grid] for tag_key in tag_types
    }
    present: dict[str, list[bool]] = {tag_key: [False for _ in grid] for tag_key in tag_types}
    for (tag_key, minute), sample in chosen.items():
        index = grid_index[minute]
        present[tag_key][index] = True
        if sample.value is not None:
            values[tag_key][index] = _normalize(sample.value, tag_types[tag_key])

    missing_by_index: list[list[str]] = []
    good = []
    for index in range(len(grid)):
        missing = sorted(
            tag_key
            for tag_key in tag_types
            if not present[tag_key][index] or values[tag_key][index] is None
        )
        missing_by_index.append(missing)
        good.append(not missing)

    max_delta = max((condition.delta_window_minutes or 0 for condition in conditions), default=0)
    system: list[SystemState | None] = [None for _ in grid]
    for index in range(len(grid)):
        if not good[index]:
            system[index] = SystemState.DATA_GAP
        elif max_delta:
            history_start = index - max_delta
            if history_start < 0 or not all(good[history_start : index + 1]):
                system[index] = SystemState.INSUFFICIENT_HISTORY

    raw_by_condition: dict[int, list[bool | None]] = {}
    refs_by_condition: dict[int, list[tuple[datetime, object] | None]] = {}
    for condition in conditions:
        raw: list[bool | None] = [None for _ in grid]
        refs: list[tuple[datetime, object] | None] = [None for _ in grid]
        for index, _minute in enumerate(grid):
            if system[index] is not None:
                continue
            reference = None
            if condition.is_delta:
                reference_index = index - (condition.delta_window_minutes or 0)
                reference = values[condition.tag_key][reference_index]
                refs[index] = (grid[reference_index], reference)
            raw[index] = _raw_predicate(condition, values[condition.tag_key][index], reference)  # type: ignore[arg-type]
        raw_by_condition[condition.id] = raw
        refs_by_condition[condition.id] = refs

    lane_by_condition: dict[int, list[LaneState]] = {}
    triggers_by_condition: dict[int, list[datetime | None]] = {}
    confirms_by_condition: dict[int, list[datetime | None]] = {}
    for condition in conditions:
        lane, triggers, confirms = _duration_states(
            condition, raw_by_condition[condition.id], system, grid
        )
        lane_by_condition[condition.id] = lane
        triggers_by_condition[condition.id] = triggers
        confirms_by_condition[condition.id] = confirms

    identities: list[str] = []
    primary_states: list[SystemState] = []
    contributors: list[tuple[int, ...]] = []
    group_results_by_index: list[dict[int, bool]] = []
    root_results: list[bool] = []
    visible_offset = grid_index[start]
    for index in range(visible_offset, len(grid)):
        group_results: dict[int, bool] = {}
        group_contributors: dict[int, set[int]] = {}
        for group in rule.groups:
            active = {
                condition.id
                for condition in group.conditions
                if lane_by_condition[condition.id][index] is LaneState.ACTIVE
            }
            satisfied = _logic(
                group.operator, [condition.id in active for condition in group.conditions]
            )
            group_results[group.id] = satisfied
            group_contributors[group.id] = active if satisfied else set()
        root = _logic(rule.root_operator, list(group_results.values()))
        contribution: set[int] = set()
        if root:
            for group in rule.groups:
                if group_results[group.id]:
                    contribution.update(group_contributors[group.id])
        if system[index] is SystemState.DATA_GAP:
            state, identity, contribution = SystemState.DATA_GAP, "DATA_GAP", set()
            root = False
        elif system[index] is SystemState.INSUFFICIENT_HISTORY:
            state, identity, contribution = (
                SystemState.INSUFFICIENT_HISTORY,
                "INSUFFICIENT_HISTORY",
                set(),
            )
            root = False
        elif root:
            ordered = tuple(sorted(contribution))
            state, identity = SystemState.BREAK, f"BREAK:{','.join(map(str, ordered))}"
        else:
            state, identity, contribution = SystemState.NORMAL, "NORMAL", set()
        identities.append(identity)
        primary_states.append(state)
        contributors.append(tuple(sorted(contribution)))
        group_results_by_index.append(group_results)
        root_results.append(root)

    segments: list[Segment] = []
    segment_start = 0
    visible_grid = grid[visible_offset:]
    for index in range(1, len(visible_grid) + 1):
        if index == len(visible_grid) or identities[index] != identities[segment_start]:
            segments.append(
                Segment(
                    visible_grid[segment_start],
                    visible_grid[index - 1] + MINUTE,
                    primary_states[segment_start],
                    identities[segment_start],
                    contributors[segment_start],
                )
            )
            segment_start = index

    intervals: list[ConditionInterval] = []
    for condition in conditions:
        lane = lane_by_condition[condition.id][visible_offset:]
        trigger_values = triggers_by_condition[condition.id][visible_offset:]
        confirm_values = confirms_by_condition[condition.id][visible_offset:]
        interval_start = 0
        for index in range(1, len(visible_grid) + 1):
            same = (
                index < len(visible_grid)
                and lane[index] is lane[interval_start]
                and trigger_values[index] == trigger_values[interval_start]
                and confirm_values[index] == confirm_values[interval_start]
            )
            if not same:
                intervals.append(
                    ConditionInterval(
                        condition.id,
                        visible_grid[interval_start],
                        visible_grid[index - 1] + MINUTE,
                        lane[interval_start],
                        trigger_values[interval_start],
                        confirm_values[interval_start],
                    )
                )
                interval_start = index

    boundaries: list[BoundaryEvent] = []
    for segment_index, segment in enumerate(segments):
        if segment_index and segment.identity == segments[segment_index - 1].identity:
            continue
        boundary_visible_index = int((segment.start_utc - start) / MINUTE)
        absolute_index = visible_offset + boundary_visible_index
        condition_context: dict[str, object] = {}
        for condition in conditions:
            delta_reference = refs_by_condition[condition.id][absolute_index]
            pending_start = triggers_by_condition[condition.id][absolute_index]
            confirmation = confirms_by_condition[condition.id][absolute_index]
            condition_context[str(condition.id)] = {
                "tag_key": condition.tag_key,
                "display_name": condition.display_name,
                "value": _json_value(values[condition.tag_key][absolute_index]),
                "raw_predicate": raw_by_condition[condition.id][absolute_index],
                "confirmed_active": lane_by_condition[condition.id][absolute_index]
                is LaneState.ACTIVE,
                "lane_state": lane_by_condition[condition.id][absolute_index].value,
                "pending_start_utc": (
                    pending_start.isoformat() if pending_start is not None else None
                ),
                "confirmation_utc": (
                    confirmation.isoformat() if confirmation is not None else None
                ),
                "delta_reference": (
                    {
                        "timestamp": delta_reference[0].isoformat(),
                        "value": _json_value(delta_reference[1]),
                    }
                    if delta_reference is not None
                    else None
                ),
            }
        previous = segments[segment_index - 1].identity if segment_index else None
        if segment.system_state is SystemState.BREAK:
            explanation = (
                "Break expression satisfied by conditions "
                + ", ".join(map(str, segment.contributing_condition_ids))
                + "."
            )
        elif segment.system_state is SystemState.DATA_GAP:
            explanation = "Required source data is missing or NULL."
        elif segment.system_state is SystemState.INSUFFICIENT_HISTORY:
            explanation = "Continuous valid history is insufficient for a delta comparison."
        else:
            explanation = "The complete break expression is not satisfied."
        boundaries.append(
            BoundaryEvent(
                segment.start_utc,
                previous,
                segment.identity,
                segment.system_state,
                segment.contributing_condition_ids,
                explanation,
                {
                    "conditions": condition_context,
                    "groups": group_results_by_index[boundary_visible_index],
                    "root_expression_result": root_results[boundary_visible_index],
                    "missing_variables": missing_by_index[absolute_index],
                },
            )
        )

    if not segments or segments[0].start_utc != start or segments[-1].end_utc != end:
        raise AssertionError("Primary segments do not cover the requested interval")
    for previous_segment, following_segment in zip(segments, segments[1:], strict=False):
        if previous_segment.end_utc != following_segment.start_utc:
            raise AssertionError("Primary segments overlap or contain a gap")

    return SegmentationResult(
        start, end, source_row_count, tuple(segments), tuple(intervals), tuple(boundaries)
    )
