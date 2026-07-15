from decimal import Decimal

from sqlalchemy.orm import Session

from recipecontrol.domain.models import (
    Condition,
    ConditionOperator,
    DataType,
    Group,
    LogicOperator,
    RuleDefinition,
)
from recipecontrol.models import RuleVersionModel
from recipecontrol.schemas import DraftWrite


def configured_value(data_type: DataType, value: object | None) -> Decimal | str | bool | None:
    if value is None:
        return None
    if data_type is DataType.NUMERIC:
        return Decimal(str(value))
    if data_type is DataType.BOOLEAN:
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().casefold()
        if normalized in {"true", "1"}:
            return True
        if normalized in {"false", "0"}:
            return False
        raise ValueError("Boolean comparison must be true, false, 1, or 0")
    return str(value)


def version_to_domain(version: RuleVersionModel) -> RuleDefinition:
    groups = []
    for group in version.groups:
        conditions = []
        for item in group.conditions:
            data_type = DataType(item.source_data_type)
            conditions.append(
                Condition(
                    id=item.id,
                    tag_key=item.source_tag_key,
                    display_name=item.source_display_name,
                    data_type=data_type,
                    operator=ConditionOperator(item.operator),
                    duration_minutes=item.duration_minutes,
                    minimum=Decimal(item.minimum) if item.minimum is not None else None,
                    maximum=Decimal(item.maximum) if item.maximum is not None else None,
                    comparison_value=configured_value(data_type, item.comparison_value),
                    delta_amount=Decimal(item.delta_amount)
                    if item.delta_amount is not None
                    else None,
                    delta_window_minutes=item.delta_window_minutes,
                )
            )
        groups.append(Group(group.id, LogicOperator(group.internal_operator), tuple(conditions)))
    return RuleDefinition(LogicOperator(version.root_operator), tuple(groups))


def draft_to_domain(payload: DraftWrite) -> RuleDefinition:
    groups = []
    next_id = 1
    for group_index, group in enumerate(payload.groups, 1):
        conditions = []
        for item in group.conditions:
            data_type = DataType(item.source_data_type)
            conditions.append(
                Condition(
                    id=item.id or next_id,
                    tag_key=item.source_tag_key,
                    display_name=item.source_display_name,
                    data_type=data_type,
                    operator=ConditionOperator(item.operator),
                    duration_minutes=item.duration_minutes,
                    minimum=Decimal(item.minimum) if item.minimum is not None else None,
                    maximum=Decimal(item.maximum) if item.maximum is not None else None,
                    comparison_value=configured_value(data_type, item.comparison_value),
                    delta_amount=Decimal(item.delta_amount)
                    if item.delta_amount is not None
                    else None,
                    delta_window_minutes=item.delta_window_minutes,
                )
            )
            next_id += 1
        groups.append(Group(group_index, LogicOperator(group.internal_operator), tuple(conditions)))
    return RuleDefinition(LogicOperator(payload.root_operator), tuple(groups))


def replace_draft(session: Session, version: RuleVersionModel, payload: DraftWrite) -> None:
    from recipecontrol.models import RuleConditionModel, RuleGroupModel

    if version.status != "DRAFT":
        raise ValueError("Saved versions are immutable")
    version.root_operator = payload.root_operator
    version.groups.clear()
    session.flush()
    for group_position, group_payload in enumerate(payload.groups):
        group = RuleGroupModel(
            version=version,
            position=group_position,
            internal_operator=group_payload.internal_operator,
        )
        session.add(group)
        for condition_position, condition_payload in enumerate(group_payload.conditions):
            session.add(
                RuleConditionModel(
                    group=group,
                    position=condition_position,
                    source_tag_key=condition_payload.source_tag_key,
                    source_display_name=condition_payload.source_display_name,
                    source_data_type=condition_payload.source_data_type,
                    operator=condition_payload.operator,
                    minimum=condition_payload.minimum,
                    maximum=condition_payload.maximum,
                    comparison_value=condition_payload.comparison_value,
                    delta_amount=condition_payload.delta_amount,
                    delta_window_minutes=condition_payload.delta_window_minutes,
                    duration_minutes=condition_payload.duration_minutes,
                )
            )
    session.flush()
