from decimal import Decimal, InvalidOperation

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
from recipecontrol.source.base import SourceDataRepository


def configured_value(data_type: DataType, value: object | None) -> Decimal | str | bool | None:
    if value is None:
        return None
    if data_type is DataType.NUMERIC:
        try:
            return Decimal(str(value))
        except InvalidOperation as error:
            raise ValueError("Numeric comparison must be a valid number") from error
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


def decimal_value(value: str | None, name: str) -> Decimal | None:
    if value is None or not value.strip():
        return None
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{name} must be a valid number") from error


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
                    minimum=decimal_value(item.minimum, "Minimum"),
                    maximum=decimal_value(item.maximum, "Maximum"),
                    comparison_value=configured_value(data_type, item.comparison_value),
                    delta_amount=decimal_value(item.delta_amount, "Delta amount"),
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
            if item.source_data_type is None or item.source_display_name is None:
                raise ValueError("Source tag metadata has not been resolved")
            data_type = DataType(item.source_data_type)
            conditions.append(
                Condition(
                    id=item.id or next_id,
                    tag_key=item.tag_id or "",
                    display_name=item.source_display_name,
                    data_type=data_type,
                    operator=ConditionOperator(item.operator),
                    duration_minutes=item.duration_minutes,
                    minimum=decimal_value(item.minimum, "Minimum"),
                    maximum=decimal_value(item.maximum, "Maximum"),
                    comparison_value=configured_value(data_type, item.comparison_value),
                    delta_amount=decimal_value(item.delta_amount, "Delta amount"),
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
                    source_tag_key=condition_payload.tag_id,
                    source_display_name=condition_payload.source_display_name,
                    source_raw_data_type=condition_payload.source_raw_data_type,
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


def resolve_authoritative_draft(
    payload: DraftWrite, machine_key: str, source: SourceDataRepository
) -> DraftWrite:
    selected = [
        condition.tag_id or "" for group in payload.groups for condition in group.conditions
    ]
    if len(selected) != len(set(selected)):
        raise ValueError("A source tag may only be selected once in a rule version")
    resolved = {tag.key: tag for tag in source.resolve_tags(machine_key, selected)}
    missing = [key for key in selected if key not in resolved]
    if missing:
        raise ValueError(
            "One or more selected tags are nonexistent, disabled, or from another machine"
        )
    groups = []
    for group in payload.groups:
        conditions = []
        for condition in group.conditions:
            tag = resolved[condition.tag_id or ""]
            conditions.append(
                condition.model_copy(
                    update={
                        "tag_id": tag.key,
                        "source_tag_key": tag.key,
                        "source_display_name": tag.display_name,
                        "source_raw_data_type": tag.raw_data_type,
                        "source_data_type": tag.data_kind,
                    }
                )
            )
        groups.append(group.model_copy(update={"conditions": conditions}))
    return payload.model_copy(update={"groups": groups})


def version_as_draft(version: RuleVersionModel) -> DraftWrite:
    return DraftWrite.model_validate(
        {
            "root_operator": version.root_operator,
            "groups": [
                {
                    "internal_operator": group.internal_operator,
                    "conditions": [
                        {
                            "id": condition.id,
                            "tag_id": condition.source_tag_key,
                            "operator": condition.operator,
                            "minimum": condition.minimum,
                            "maximum": condition.maximum,
                            "comparison_value": condition.comparison_value,
                            "delta_amount": condition.delta_amount,
                            "delta_window_minutes": condition.delta_window_minutes,
                            "duration_minutes": condition.duration_minutes,
                        }
                        for condition in group.conditions
                    ],
                }
                for group in version.groups
            ],
        }
    )
