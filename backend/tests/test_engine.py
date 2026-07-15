from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from recipecontrol.domain.engine import RuleEvaluationError, segment_timeline
from recipecontrol.domain.models import (
    Condition,
    DataType,
    Group,
    LaneState,
    LogicOperator,
    RuleDefinition,
    SystemState,
)
from recipecontrol.domain.models import (
    ConditionOperator as Op,
)
from recipecontrol.source.base import Sample

T0 = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)


def condition(
    identifier: int = 1,
    *,
    tag: str = "a",
    data_type: DataType = DataType.NUMERIC,
    operator: Op = Op.ABOVE_MAXIMUM,
    duration: int = 0,
    minimum: str | None = None,
    maximum: str | None = "10",
    value: Decimal | str | bool | None = None,
    amount: str | None = None,
    window: int | None = None,
) -> Condition:
    return Condition(
        identifier,
        tag,
        tag.upper(),
        data_type,
        operator,
        duration,
        Decimal(minimum) if minimum is not None else None,
        Decimal(maximum) if maximum is not None else None,
        value,
        Decimal(amount) if amount is not None else None,
        window,
    )


def rule(*conditions: Condition, root: LogicOperator = LogicOperator.OR) -> RuleDefinition:
    return RuleDefinition(root, (Group(1, LogicOperator.OR, tuple(conditions)),))


def grouped(
    groups: tuple[tuple[LogicOperator, tuple[Condition, ...]], ...],
    root: LogicOperator,
) -> RuleDefinition:
    return RuleDefinition(
        root,
        tuple(
            Group(index + 1, operator, members) for index, (operator, members) in enumerate(groups)
        ),
    )


def rows(
    values: dict[str, list[object | None]],
    *,
    start: datetime = T0,
    missing: set[tuple[str, int]] | None = None,
) -> list[Sample]:
    output = []
    row_id = 1
    for tag, series in values.items():
        for index, value in enumerate(series):
            if missing and (tag, index) in missing:
                continue
            output.append(Sample(tag, start + timedelta(minutes=index, seconds=5), value, row_id))
            row_id += 1
    return output


def evaluate(
    definition: RuleDefinition,
    values: dict[str, list[object | None]],
    *,
    start: datetime = T0,
    visible_start_index: int = 0,
    end_index: int | None = None,
    missing: set[tuple[str, int]] | None = None,
):
    if end_index is None:
        end_index = len(next(iter(values.values()))) - 1
    visible_start = start + timedelta(minutes=visible_start_index)
    end = start + timedelta(minutes=end_index)
    return segment_timeline(
        definition, rows(values, start=start, missing=missing), visible_start, end
    )


def states(result) -> list[SystemState]:
    output = []
    for segment in result.segments:
        output.extend(
            [segment.system_state]
            * int((segment.end_utc - segment.start_utc) / timedelta(minutes=1))
        )
    return output


def test_below_minimum_is_strict() -> None:
    c = condition(operator=Op.BELOW_MINIMUM, minimum="10", maximum=None)
    assert states(evaluate(rule(c), {"a": [10, 9]})) == [SystemState.NORMAL, SystemState.BREAK]


def test_above_maximum_is_strict() -> None:
    assert states(evaluate(rule(condition()), {"a": [10, 11]})) == [
        SystemState.NORMAL,
        SystemState.BREAK,
    ]


def test_outside_range_boundaries_are_inclusive() -> None:
    c = condition(operator=Op.OUTSIDE_RANGE, minimum="10", maximum="20")
    assert states(evaluate(rule(c), {"a": [9, 10, 20, 21]})) == [
        SystemState.BREAK,
        SystemState.NORMAL,
        SystemState.NORMAL,
        SystemState.BREAK,
    ]


@pytest.mark.parametrize(
    ("operator", "expected"),
    [
        (Op.EQUALS, [SystemState.BREAK, SystemState.NORMAL]),
        (Op.NOT_EQUALS, [SystemState.NORMAL, SystemState.BREAK]),
    ],
)
def test_numeric_equality_is_exact(operator: Op, expected: list[SystemState]) -> None:
    c = condition(operator=operator, maximum=None, value=Decimal("1.00"))
    assert states(evaluate(rule(c), {"a": ["1.0", "1.01"]})) == expected


@pytest.mark.parametrize("operator", [Op.EQUALS, Op.NOT_EQUALS])
def test_text_equals_and_not_equals(operator: Op) -> None:
    c = condition(data_type=DataType.TEXT, operator=operator, maximum=None, value="Alarm")
    result = states(evaluate(rule(c), {"a": ["Alarm", "alarm"]}))
    expected = [SystemState.BREAK, SystemState.NORMAL]
    assert result == (expected if operator is Op.EQUALS else list(reversed(expected)))


@pytest.mark.parametrize("source", [True, 1, "1", "true", "TRUE"])
def test_boolean_normalization(source: object) -> None:
    c = condition(data_type=DataType.BOOLEAN, operator=Op.EQUALS, maximum=None, value=True)
    assert states(evaluate(rule(c), {"a": [source]})) == [SystemState.BREAK]


def test_boolean_comparison_false() -> None:
    c = condition(data_type=DataType.BOOLEAN, operator=Op.NOT_EQUALS, maximum=None, value=True)
    assert states(evaluate(rule(c), {"a": [False]})) == [SystemState.BREAK]


def test_delta_increase_uses_absolute_amount() -> None:
    c = condition(operator=Op.INCREASE_BY, maximum=None, amount="5", window=2)
    result = evaluate(rule(c), {"a": [10, 12, 15, 16]}, visible_start_index=2)
    assert states(result) == [SystemState.BREAK, SystemState.NORMAL]


def test_delta_decrease() -> None:
    c = condition(operator=Op.DECREASE_BY, maximum=None, amount="5", window=2)
    result = evaluate(rule(c), {"a": [20, 18, 15]}, visible_start_index=2)
    assert states(result) == [SystemState.BREAK]


def test_delta_uses_exact_lookback_minute() -> None:
    c = condition(operator=Op.INCREASE_BY, maximum=None, amount="6", window=2)
    result = evaluate(rule(c), {"a": [10, 100, 16]}, visible_start_index=2)
    assert states(result) == [SystemState.BREAK]
    reference = result.boundaries[0].context["conditions"]["1"]["delta_reference"]
    assert reference["timestamp"] == T0.isoformat()


def test_zero_duration_activates_first_true_minute() -> None:
    assert states(evaluate(rule(condition()), {"a": [11]})) == [SystemState.BREAK]


def test_positive_duration_confirms_and_backdates() -> None:
    c = condition(duration=5)
    result = evaluate(rule(c), {"a": [9, 11, 11, 11, 11, 11]})
    assert [
        (segment.start_utc, segment.end_utc, segment.system_state) for segment in result.segments
    ] == [
        (T0, T0 + timedelta(minutes=1), SystemState.NORMAL),
        (T0 + timedelta(minutes=1), T0 + timedelta(minutes=6), SystemState.BREAK),
    ]
    active = next(item for item in result.condition_intervals if item.state is LaneState.ACTIVE)
    assert active.trigger_utc == T0 + timedelta(minutes=1)
    assert active.confirmation_utc == T0 + timedelta(minutes=5)


def test_pending_at_analysis_end_does_not_split() -> None:
    c = condition(duration=5)
    result = evaluate(rule(c), {"a": [9, 11, 11, 11]})
    assert len(result.segments) == 1 and result.segments[0].system_state is SystemState.NORMAL
    assert any(item.state is LaneState.PENDING for item in result.condition_intervals)


def test_recovery_is_immediate() -> None:
    c = condition(duration=2)
    assert states(evaluate(rule(c), {"a": [11, 11, 10]})) == [
        SystemState.BREAK,
        SystemState.BREAK,
        SystemState.NORMAL,
    ]


def test_partial_and_does_not_split_primary() -> None:
    first, second = condition(1, tag="a"), condition(2, tag="b")
    definition = grouped(((LogicOperator.AND, (first, second)),), LogicOperator.OR)
    result = evaluate(definition, {"a": [11], "b": [5]})
    assert states(result) == [SystemState.NORMAL]
    assert (
        next(item for item in result.condition_intervals if item.condition_id == 1).state
        is LaneState.ACTIVE
    )


def test_grouped_or_expression() -> None:
    a, b = condition(1, tag="a"), condition(2, tag="b")
    definition = grouped(((LogicOperator.AND, (a,)), (LogicOperator.AND, (b,))), LogicOperator.OR)
    assert states(evaluate(definition, {"a": [5], "b": [11]})) == [SystemState.BREAK]


def test_grouped_and_root_expression() -> None:
    a, b = condition(1, tag="a"), condition(2, tag="b")
    definition = grouped(((LogicOperator.OR, (a,)), (LogicOperator.OR, (b,))), LogicOperator.AND)
    assert states(evaluate(definition, {"a": [11, 11], "b": [5, 11]})) == [
        SystemState.NORMAL,
        SystemState.BREAK,
    ]


def test_contributing_set_changes_make_segments() -> None:
    a, b = condition(1, tag="a"), condition(2, tag="b")
    result = evaluate(rule(a, b), {"a": [11, 11, 5], "b": [5, 11, 11]})
    assert [segment.contributing_condition_ids for segment in result.segments] == [
        (1,),
        (1, 2),
        (2,),
    ]


def test_missing_row_creates_data_gap() -> None:
    result = evaluate(rule(condition()), {"a": [5, 5]}, missing={("a", 1)})
    assert states(result)[1] is SystemState.DATA_GAP


def test_null_creates_data_gap() -> None:
    assert states(evaluate(rule(condition()), {"a": [None]})) == [SystemState.DATA_GAP]


def test_changing_missing_variables_is_one_gap() -> None:
    a, b = condition(1, tag="a"), condition(2, tag="b")
    result = evaluate(rule(a, b), {"a": [None, 1], "b": [1, None]})
    assert len(result.segments) == 1 and result.segments[0].system_state is SystemState.DATA_GAP


def test_data_gap_overrides_true_break() -> None:
    a, b = condition(1, tag="a"), condition(2, tag="b")
    result = evaluate(rule(a, b), {"a": [11], "b": [None]})
    assert states(result) == [SystemState.DATA_GAP]


def test_return_from_gap_has_insufficient_delta_history() -> None:
    c = condition(operator=Op.INCREASE_BY, maximum=None, amount="5", window=2)
    result = evaluate(rule(c), {"a": [1, None, 2, 3, 8]}, visible_start_index=1)
    assert states(result) == [
        SystemState.DATA_GAP,
        SystemState.INSUFFICIENT_HISTORY,
        SystemState.INSUFFICIENT_HISTORY,
        SystemState.BREAK,
    ]


def test_no_insufficient_history_without_delta() -> None:
    result = evaluate(rule(condition()), {"a": [None, 11]})
    assert states(result) == [SystemState.DATA_GAP, SystemState.BREAK]


def test_preload_determines_visible_start_state() -> None:
    c = condition(duration=3)
    result = evaluate(rule(c), {"a": [11, 11, 11, 11]}, visible_start_index=3)
    assert states(result) == [SystemState.BREAK]


def test_latest_sample_in_minute_wins() -> None:
    c = condition()
    samples = [
        Sample("a", T0 + timedelta(seconds=1), 5, 1),
        Sample("a", T0 + timedelta(seconds=59), 11, 2),
    ]
    assert states(segment_timeline(rule(c), samples, T0, T0)) == [SystemState.BREAK]


def test_tied_timestamp_uses_greatest_tie_breaker() -> None:
    c = condition()
    samples = [Sample("a", T0, 5, 1), Sample("a", T0, 11, 2)]
    assert states(segment_timeline(rule(c), samples, T0, T0)) == [SystemState.BREAK]


def test_complete_coverage_has_no_gaps_or_overlap() -> None:
    result = evaluate(rule(condition()), {"a": [5, 11, None, 5]})
    assert result.segments[0].start_utc == T0
    assert result.segments[-1].end_utc == T0 + timedelta(minutes=4)
    assert all(
        a.end_utc == b.start_utc for a, b in zip(result.segments, result.segments[1:], strict=False)
    )


def test_inclusive_selected_end_and_minute_clipping() -> None:
    result = evaluate(rule(condition()), {"a": [5, 5, 5]}, visible_start_index=1, end_index=1)
    assert result.start_utc == T0 + timedelta(minutes=1)
    assert result.end_utc == T0 + timedelta(minutes=2)


def test_non_minute_input_rejected() -> None:
    with pytest.raises(RuleEvaluationError, match="minute precision"):
        segment_timeline(rule(condition()), [], T0 + timedelta(seconds=1), T0)


def test_analysis_end_pending_is_not_confirmed_by_data_after_end() -> None:
    c = condition(duration=3)
    result = evaluate(rule(c), {"a": [11, 11, 11]}, end_index=1)
    assert states(result) == [SystemState.NORMAL, SystemState.NORMAL]
