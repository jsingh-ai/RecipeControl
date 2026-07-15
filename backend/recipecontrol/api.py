import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import case, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from recipecontrol.config import get_settings
from recipecontrol.database import as_utc, get_session, utc_now
from recipecontrol.domain.engine import RuleEvaluationError, validate_rule
from recipecontrol.models import (
    AnalysisJobModel,
    AnalysisMinuteModel,
    AnalysisModel,
    BoundaryEventModel,
    ClassificationModel,
    ConditionIntervalModel,
    LabelHistoryModel,
    LiveSessionModel,
    MachineModel,
    RuleSetModel,
    RuleVersionModel,
    SegmentModel,
)
from recipecontrol.schemas import (
    AnalysisCreate,
    ClassificationCreate,
    DraftWrite,
    LiveCreate,
    MachineOut,
    RuleSetCreate,
    SegmentLabelUpdate,
    TagOut,
)
from recipecontrol.services import (
    draft_to_domain,
    replace_draft,
    resolve_authoritative_draft,
    sync_machine_catalog,
    version_as_draft,
    version_to_domain,
)
from recipecontrol.source import dispose_source_repository, get_source_repository
from recipecontrol.source.base import Tag

logger = logging.getLogger("recipecontrol.api")
router = APIRouter(prefix="/api")
SessionDep = Annotated[Session, Depends(get_session)]


def _version_dict(version: RuleVersionModel) -> dict[str, object]:
    return {
        "id": version.id,
        "rule_set_id": version.rule_set_id,
        "version_number": version.version_number,
        "root_operator": version.root_operator,
        "status": version.status,
        "created_at": as_utc(version.created_at),
        "locked_at": as_utc(version.locked_at) if version.locked_at else None,
        "groups": [
            {
                "id": group.id,
                "position": group.position,
                "internal_operator": group.internal_operator,
                "conditions": [
                    {
                        "id": item.id,
                        "position": item.position,
                        "source_tag_key": item.source_tag_key,
                        "source_display_name": item.source_display_name,
                        "source_raw_data_type": item.source_raw_data_type,
                        "source_data_type": item.source_data_type,
                        "operator": item.operator,
                        "minimum": item.minimum,
                        "maximum": item.maximum,
                        "comparison_value": item.comparison_value,
                        "delta_amount": item.delta_amount,
                        "delta_window_minutes": item.delta_window_minutes,
                        "duration_minutes": item.duration_minutes,
                    }
                    for item in group.conditions
                ],
            }
            for group in version.groups
        ],
    }


def _analysis_dict(analysis: AnalysisModel) -> dict[str, object]:
    return {
        "id": analysis.id,
        "title": analysis.title,
        "machine_id": analysis.machine_id,
        "rule_version_id": analysis.rule_version_id,
        "selected_start_utc": as_utc(analysis.selected_start_utc),
        "selected_end_utc": as_utc(analysis.selected_end_utc),
        "end_exclusive_utc": as_utc(analysis.end_exclusive_utc),
        "mode": analysis.mode,
        "status": analysis.status,
        "duplicate_of_analysis_id": analysis.duplicate_of_analysis_id,
        "source_row_count": analysis.source_row_count,
        "error_message": analysis.error_message,
        "created_at": as_utc(analysis.created_at),
        "completed_at_utc": as_utc(analysis.completed_at) if analysis.completed_at else None,
    }


def _segment_dict(segment: SegmentModel) -> dict[str, object]:
    return {
        "id": segment.id,
        "analysis_id": segment.analysis_id,
        "start_utc": as_utc(segment.start_utc),
        "end_utc": as_utc(segment.end_utc),
        "system_state": segment.system_state,
        "identity_key": segment.identity_key,
        "contributing_condition_ids": segment.contributing_condition_ids,
        "quality_label": segment.quality_label,
        "classification_id": segment.classification_id,
        "classification_name": segment.classification_name_snapshot,
        "note": segment.note,
        "active_live": segment.active_live,
        "training_eligible": segment.training_eligible,
        "label_updated_at": (
            as_utc(segment.label_updated_at) if segment.label_updated_at else None
        ),
    }


@router.get("/health")
async def health(session: SessionDep) -> dict[str, object]:
    checks: dict[str, object] = {"api": {"ok": True}}
    try:
        session.execute(text("SELECT 1"))
        checks["app_database"] = {"ok": True}
    except Exception:
        logger.exception("app_database_health_failed")
        checks["app_database"] = {"ok": False}
    try:
        checks["source_database"] = get_source_repository().health()
    except Exception:
        logger.exception("source_database_health_failed")
        checks["source_database"] = {"ok": False, "error": "Source database unavailable"}
    checks["ready"] = all(
        bool(value.get("ok")) for value in checks.values() if isinstance(value, dict)
    )
    return checks


@router.get("/machines", response_model=list[MachineOut])
async def machines(session: SessionDep, include_inactive: bool = False) -> list[MachineModel]:
    try:
        sync_machine_catalog(session, list(get_source_repository().list_machines()))
        session.commit()
    except Exception as error:
        session.rollback()
        raise HTTPException(503, "Source database unavailable") from error
    statement = select(MachineModel)
    if not include_inactive:
        statement = statement.where(MachineModel.enabled)
    return list(session.scalars(statement.order_by(MachineModel.name, MachineModel.id)))


@router.get("/machines/{machine_id}/tags")
async def tags(
    machine_id: int,
    session: SessionDep,
    q: str = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    machine = session.get(MachineModel, machine_id)
    if machine is None:
        raise HTTPException(404, "Machine not found")
    try:
        page = get_source_repository().search_tags(
            machine.source_key, q, limit=limit, offset=offset
        )
    except Exception as error:
        raise HTTPException(503, "Source database unavailable") from error
    return {
        "items": [
            TagOut(
                key=tag.key,
                display_name=tag.display_name,
                raw_data_type=tag.raw_data_type,
                data_kind=tag.data_kind,
                units=tag.units,
                node_id=tag.node_id,
                opc_path=tag.opc_path,
            ).model_dump()
            for tag in page.items
        ],
        "limit": page.limit,
        "offset": page.offset,
        "has_more": page.has_more,
    }


@router.get("/rule-sets")
async def list_rule_sets(
    session: SessionDep, machine_id: int | None = None, include_archived: bool = False
) -> list[dict[str, object]]:
    statement = select(RuleSetModel).options(selectinload(RuleSetModel.versions))
    if machine_id is not None:
        statement = statement.where(RuleSetModel.machine_id == machine_id)
    if not include_archived:
        statement = statement.where(RuleSetModel.archived.is_(False))
    return [
        {
            "id": item.id,
            "machine_id": item.machine_id,
            "name": item.name,
            "archived": item.archived,
            "versions": [
                _version_dict(version)
                for version in sorted(
                    item.versions, key=lambda value: (value.version_number, value.id)
                )
            ],
        }
        for item in session.scalars(statement.order_by(RuleSetModel.name)).unique()
    ]


@router.post("/rule-sets", status_code=201)
async def create_rule_set(payload: RuleSetCreate, session: SessionDep) -> dict[str, object]:
    machine = session.get(MachineModel, payload.machine_id)
    if machine is None:
        raise HTTPException(404, "Machine not found")
    if not machine.enabled:
        raise HTTPException(422, "New definitions require an active source machine")
    item = RuleSetModel(machine_id=payload.machine_id, name=payload.name.strip())
    version = RuleVersionModel(version_number=1, root_operator="OR", status="DRAFT")
    item.versions.append(version)
    session.add(item)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            409, "A definition with that name already exists for this machine"
        ) from error
    return {"rule_set_id": item.id, "version": _version_dict(version)}


@router.get("/rule-versions/{version_id}")
async def get_version(version_id: int, session: SessionDep) -> dict[str, object]:
    version = session.get(RuleVersionModel, version_id)
    if version is None:
        raise HTTPException(404, "Rule version not found")
    return _version_dict(version)


@router.post("/rule-versions/validate")
async def validate_draft(payload: DraftWrite) -> dict[str, object]:
    try:
        definition = draft_to_domain(payload)
        validate_rule(definition)
        return {"valid": True, "preload_minutes": definition.preload_minutes}
    except (ValueError, RuleEvaluationError) as error:
        raise HTTPException(422, str(error)) from error


@router.put("/rule-versions/{version_id}")
async def update_draft(
    version_id: int, payload: DraftWrite, session: SessionDep
) -> dict[str, object]:
    version = session.get(RuleVersionModel, version_id)
    if version is None:
        raise HTTPException(404, "Rule version not found")
    if version.rule_set.archived or not version.rule_set.machine.enabled:
        raise HTTPException(422, "Drafts require an active, non-archived definition")
    try:
        resolved = resolve_authoritative_draft(
            payload, version.rule_set.machine.source_key, get_source_repository()
        )
        validate_rule(draft_to_domain(resolved))
        replace_draft(session, version, resolved)
        session.commit()
    except (ValueError, RuleEvaluationError) as error:
        session.rollback()
        raise HTTPException(422, str(error)) from error
    except Exception as error:
        session.rollback()
        logger.exception("source_tag_resolution_failed")
        raise HTTPException(503, "Source database unavailable") from error
    return _version_dict(version)


@router.post("/rule-versions/{version_id}/lock")
async def lock_version(version_id: int, session: SessionDep) -> dict[str, object]:
    version = session.get(RuleVersionModel, version_id)
    if version is None:
        raise HTTPException(404, "Rule version not found")
    if version.status == "LOCKED":
        return _version_dict(version)
    if version.rule_set.archived or not version.rule_set.machine.enabled:
        raise HTTPException(422, "Drafts require an active, non-archived definition")
    try:
        resolved = resolve_authoritative_draft(
            version_as_draft(version),
            version.rule_set.machine.source_key,
            get_source_repository(),
        )
        replace_draft(session, version, resolved)
        validate_rule(version_to_domain(version))
    except (ValueError, RuleEvaluationError) as error:
        session.rollback()
        raise HTTPException(422, str(error)) from error
    except Exception as error:
        session.rollback()
        logger.exception("source_tag_resolution_failed")
        raise HTTPException(503, "Source database unavailable") from error
    version.status = "LOCKED"
    version.locked_at = utc_now()
    session.commit()
    return _version_dict(version)


@router.post("/rule-sets/{rule_set_id}/versions", status_code=201)
async def new_blank_version(rule_set_id: int, session: SessionDep) -> dict[str, object]:
    item = session.get(RuleSetModel, rule_set_id)
    if item is None:
        raise HTTPException(404, "Rule set not found")
    if item.archived:
        raise HTTPException(422, "Archived definitions cannot create new versions")
    if not item.machine.enabled:
        raise HTTPException(422, "New versions require an active source machine")
    latest = session.scalar(
        select(func.max(RuleVersionModel.version_number)).where(
            RuleVersionModel.rule_set_id == rule_set_id
        )
    )
    version = RuleVersionModel(
        rule_set_id=rule_set_id,
        version_number=(latest or 0) + 1,
        root_operator="OR",
        status="DRAFT",
    )
    session.add(version)
    session.commit()
    return _version_dict(version)


@router.post("/rule-sets/{rule_set_id}/archive")
async def archive_rule_set(rule_set_id: int, session: SessionDep) -> dict[str, bool]:
    item = session.get(RuleSetModel, rule_set_id)
    if item is None:
        raise HTTPException(404, "Rule set not found")
    item.archived = True
    session.commit()
    return {"archived": True}


@router.get("/rule-versions/{version_id}/classifications")
async def classifications(
    version_id: int, session: SessionDep, include_inactive: bool = False
) -> list[dict[str, object]]:
    statement = select(ClassificationModel).where(ClassificationModel.rule_version_id == version_id)
    if not include_inactive:
        statement = statement.where(ClassificationModel.active)
    return [
        {"id": item.id, "name": item.name, "active": item.active, "retired_at": item.retired_at}
        for item in session.scalars(statement.order_by(ClassificationModel.name))
    ]


@router.post("/rule-versions/{version_id}/classifications", status_code=201)
async def create_classification(
    version_id: int, payload: ClassificationCreate, session: SessionDep
) -> dict[str, object]:
    version = session.get(RuleVersionModel, version_id)
    if version is None or version.status != "LOCKED":
        raise HTTPException(422, "Classifications require a saved rule version")
    item = ClassificationModel(rule_version_id=version_id, name=payload.name)
    session.add(item)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(409, "Classification already exists") from error
    return {"id": item.id, "name": item.name, "active": item.active}


@router.delete("/classifications/{classification_id}")
async def retire_classification(classification_id: int, session: SessionDep) -> dict[str, bool]:
    item = session.get(ClassificationModel, classification_id)
    if item is None:
        raise HTTPException(404, "Classification not found")
    item.active = False
    item.retired_at = utc_now()
    session.commit()
    return {"active": False}


def _duplicates(
    session: Session, payload: AnalysisCreate, mode: str = "HISTORICAL"
) -> list[AnalysisModel]:
    complete_first = case((AnalysisModel.status == "COMPLETE", 0), else_=1)
    return list(
        session.scalars(
            select(AnalysisModel)
            .where(
                AnalysisModel.machine_id == payload.machine_id,
                AnalysisModel.rule_version_id == payload.rule_version_id,
                AnalysisModel.selected_start_utc == payload.selected_start_utc,
                AnalysisModel.selected_end_utc == payload.selected_end_utc,
                AnalysisModel.mode == mode,
            )
            .order_by(
                complete_first,
                AnalysisModel.completed_at.desc(),
                AnalysisModel.id.desc(),
            )
        )
    )


@router.post("/analyses/check-duplicate")
async def check_duplicate(payload: AnalysisCreate, session: SessionDep) -> dict[str, object]:
    matches = _duplicates(session, payload)
    return {"duplicate": bool(matches), "matches": [_analysis_dict(item) for item in matches]}


@router.post("/analyses", status_code=202, response_model=None)
async def create_analysis(
    payload: AnalysisCreate, session: SessionDep
) -> dict[str, object] | JSONResponse:
    settings = get_settings()
    if payload.end_exclusive - payload.selected_start_utc > timedelta(
        days=settings.max_analysis_days
    ):
        raise HTTPException(422, f"Analysis span exceeds {settings.max_analysis_days} days")
    machine = session.get(MachineModel, payload.machine_id)
    version = session.get(RuleVersionModel, payload.rule_version_id)
    if machine is None or version is None:
        raise HTTPException(404, "Machine or rule version not found")
    if not machine.enabled:
        raise HTTPException(422, "New analyses require an active source machine")
    if version.rule_set.archived:
        raise HTTPException(422, "Archived definitions cannot create new analyses")
    if version.status != "LOCKED" or version.rule_set.machine_id != machine.id:
        raise HTTPException(422, "Analysis requires a saved version for the selected machine")
    matches = _duplicates(session, payload)
    if matches and not payload.create_duplicate:
        return JSONResponse(
            status_code=409,
            content={
                "code": "DUPLICATE_ANALYSIS",
                "message": "An analysis already exists for this definition and period.",
                "matches": [
                    {
                        "id": item.id,
                        "status": item.status,
                        "title": item.title,
                        "completed_at_utc": (
                            as_utc(item.completed_at).isoformat() if item.completed_at else None
                        ),
                    }
                    for item in matches
                ],
            },
        )
    analysis = AnalysisModel(
        title=payload.title,
        machine_id=payload.machine_id,
        rule_version_id=payload.rule_version_id,
        selected_start_utc=payload.selected_start_utc,
        selected_end_utc=payload.selected_end_utc,
        end_exclusive_utc=payload.end_exclusive,
        mode="HISTORICAL",
        status="QUEUED",
        duplicate_of_analysis_id=matches[0].id if matches else None,
    )
    session.add(analysis)
    session.flush()
    session.add(AnalysisJobModel(analysis_id=analysis.id, state="QUEUED"))
    session.commit()
    return _analysis_dict(analysis)


@router.get("/analyses")
async def list_analyses(
    session: SessionDep,
    machine_id: int | None = None,
    rule_version_id: int | None = None,
) -> list[dict[str, object]]:
    statement = select(AnalysisModel)
    if machine_id is not None:
        statement = statement.where(AnalysisModel.machine_id == machine_id)
    if rule_version_id is not None:
        statement = statement.where(AnalysisModel.rule_version_id == rule_version_id)
    return [
        _analysis_dict(item)
        for item in session.scalars(statement.order_by(AnalysisModel.created_at.desc()))
    ]


@router.get("/analyses/{analysis_id}")
async def get_analysis(analysis_id: int, session: SessionDep) -> dict[str, object]:
    item = session.get(AnalysisModel, analysis_id)
    if item is None:
        raise HTTPException(404, "Analysis not found")
    result = _analysis_dict(item)
    job = session.scalar(select(AnalysisJobModel).where(AnalysisJobModel.analysis_id == item.id))
    result["job"] = (
        {
            "id": job.id,
            "state": job.state,
            "attempt_count": job.attempt_count,
            "heartbeat_at": job.heartbeat_at,
        }
        if job
        else None
    )
    return result


@router.get("/analyses/{analysis_id}/timeline")
async def timeline(analysis_id: int, session: SessionDep) -> dict[str, object]:
    analysis = session.get(AnalysisModel, analysis_id)
    if analysis is None:
        raise HTTPException(404, "Analysis not found")
    segments = session.scalars(
        select(SegmentModel)
        .where(SegmentModel.analysis_id == analysis_id)
        .order_by(SegmentModel.start_utc)
    )
    intervals = session.scalars(
        select(ConditionIntervalModel)
        .where(ConditionIntervalModel.analysis_id == analysis_id)
        .order_by(ConditionIntervalModel.condition_id, ConditionIntervalModel.start_utc)
    )
    boundaries = session.scalars(
        select(BoundaryEventModel)
        .where(BoundaryEventModel.analysis_id == analysis_id)
        .order_by(BoundaryEventModel.boundary_utc)
    )
    return {
        "analysis": _analysis_dict(analysis),
        "segments": [_segment_dict(item) for item in segments],
        "condition_intervals": [
            {
                "id": item.id,
                "condition_id": item.condition_id,
                "start_utc": as_utc(item.start_utc),
                "end_utc": as_utc(item.end_utc),
                "state": item.state,
                "trigger_utc": as_utc(item.trigger_utc) if item.trigger_utc else None,
                "confirmation_utc": (
                    as_utc(item.confirmation_utc) if item.confirmation_utc else None
                ),
            }
            for item in intervals
        ],
        "conditions": [
            {
                "id": condition.id,
                "tag_id": condition.source_tag_key,
                "display_name": condition.source_display_name,
                "raw_data_type": condition.source_raw_data_type,
                "data_kind": condition.source_data_type,
                "operator": condition.operator,
                "minimum": condition.minimum,
                "maximum": condition.maximum,
                "comparison_value": condition.comparison_value,
                "delta_amount": condition.delta_amount,
                "delta_window_minutes": condition.delta_window_minutes,
                "duration_minutes": condition.duration_minutes,
            }
            for group in analysis.rule_version.groups
            for condition in group.conditions
        ],
        "boundaries": [
            {
                "id": item.id,
                "boundary_utc": as_utc(item.boundary_utc),
                "previous_identity": item.previous_identity,
                "next_identity": item.next_identity,
                "event_type": item.event_type,
                "explanation": item.explanation,
                "context": item.context,
            }
            for item in boundaries
        ],
    }


@router.get("/analyses/{analysis_id}/minutes/{minute_utc}")
async def exact_minute(
    analysis_id: int, minute_utc: datetime, session: SessionDep
) -> dict[str, object]:
    if minute_utc.tzinfo is None or minute_utc.second or minute_utc.microsecond:
        raise HTTPException(422, "minute_utc must be a timezone-aware minute")
    minute = minute_utc.astimezone(UTC)
    item = session.scalar(
        select(AnalysisMinuteModel).where(
            AnalysisMinuteModel.analysis_id == analysis_id,
            AnalysisMinuteModel.minute_utc == minute,
        )
    )
    if item is None:
        raise HTTPException(404, "Exact-minute evaluation not found")
    segment = session.get(SegmentModel, item.segment_id)
    if segment is None:
        raise HTTPException(404, "Minute segment not found")
    if segment.system_state in {"DATA_GAP", "INSUFFICIENT_HISTORY"}:
        training_reason = f"{segment.system_state.replace('_', ' ').title()} is training-ineligible"
    elif segment.quality_label not in {"GOOD", "BAD"}:
        training_reason = "A Good or Bad label is required"
    else:
        training_reason = None
    return {
        "analysis_id": analysis_id,
        "minute_utc": minute,
        "segment": _segment_dict(segment),
        **item.snapshot,
        "training_eligible": segment.training_eligible,
        "training_ineligibility_reason": training_reason,
    }


@router.get("/analyses/{analysis_id}/boundaries")
async def boundary_events(analysis_id: int, session: SessionDep) -> list[dict[str, object]]:
    return (await timeline(analysis_id, session))["boundaries"]  # type: ignore[return-value]


@router.get("/segments/{segment_id}")
async def get_segment(segment_id: int, session: SessionDep) -> dict[str, object]:
    item = session.get(SegmentModel, segment_id)
    if item is None:
        raise HTTPException(404, "Segment not found")
    return _segment_dict(item)


@router.patch("/analyses/{analysis_id}/segments/{segment_id}")
async def update_segment(
    analysis_id: int, segment_id: int, payload: SegmentLabelUpdate, session: SessionDep
) -> dict[str, object]:
    settings = get_settings()
    if payload.note is not None and len(payload.note) > settings.note_max_length:
        raise HTTPException(422, f"Note cannot exceed {settings.note_max_length} characters")
    segment = session.get(SegmentModel, segment_id)
    if segment is None:
        raise HTTPException(404, "Segment not found")
    if segment.analysis_id != analysis_id:
        raise HTTPException(409, "Segment does not belong to the selected analysis")
    analysis = session.get(AnalysisModel, analysis_id)
    if analysis is None:
        raise HTTPException(404, "Analysis not found")
    classification = None
    if payload.classification_id is not None:
        classification = session.get(ClassificationModel, payload.classification_id)
        if (
            classification is None
            or not classification.active
            or analysis is None
            or classification.rule_version_id != analysis.rule_version_id
        ):
            raise HTTPException(422, "Classification is unavailable for this rule version")
    segment.quality_label = payload.quality_label
    segment.classification_id = classification.id if classification else None
    segment.classification_name_snapshot = classification.name if classification else None
    segment.note = payload.note
    segment.label_updated_at = utc_now()
    session.add(
        LabelHistoryModel(
            segment_id=segment.id,
            quality_label=segment.quality_label,
            classification_id=segment.classification_id,
            classification_name_snapshot=segment.classification_name_snapshot,
            note=segment.note,
        )
    )
    session.commit()
    return _segment_dict(segment)


@router.get("/analyses/{analysis_id}/trends")
async def trends(
    analysis_id: int,
    clicked_utc: datetime,
    session: SessionDep,
    lookback_minutes: Annotated[int, Query(ge=1)] = 15,
    tag_ids: Annotated[list[str] | None, Query()] = None,
) -> dict[str, object]:
    settings = get_settings()
    if lookback_minutes > settings.max_trend_lookback_minutes:
        raise HTTPException(422, "Trend lookback exceeds configured maximum")
    if clicked_utc.tzinfo is None:
        raise HTTPException(422, "clicked_utc must include timezone")
    clicked = clicked_utc.astimezone(UTC).replace(second=0, microsecond=0)
    analysis = session.get(AnalysisModel, analysis_id)
    if analysis is None:
        raise HTTPException(404, "Analysis not found")
    snapshot_metadata: dict[str, Tag] = {}
    for condition in analysis.rule_version.groups:
        for item in condition.conditions:
            snapshot_metadata.setdefault(
                item.source_tag_key,
                Tag(
                    item.source_tag_key,
                    analysis.machine.source_key,
                    item.source_display_name,
                    item.source_raw_data_type,
                    item.source_data_type,
                ),
            )
    default_tags = sorted(snapshot_metadata)
    extras = [tag for tag in (tag_ids or []) if tag not in snapshot_metadata]
    requested = [*default_tags, *dict.fromkeys(extras)]
    machine = session.get(MachineModel, analysis.machine_id)
    assert machine is not None
    source = get_source_repository()
    metadata = dict(snapshot_metadata)
    if extras:
        current = {tag.key: tag for tag in source.resolve_tags(machine.source_key, extras)}
        if any(tag not in current for tag in extras):
            raise HTTPException(422, "Temporary tags must be enabled and belong to the machine")
        metadata.update(current)
    start = clicked - timedelta(minutes=lookback_minutes - 1)
    chosen: dict[tuple[str, datetime], object] = {}
    ranks: dict[tuple[str, datetime], tuple[datetime, str]] = {}
    tag_kinds = {tag: metadata[tag].data_kind for tag in requested}
    for sample in source.get_samples(
        machine.source_key, tag_kinds, start, clicked + timedelta(minutes=1)
    ):
        stamp = (
            sample.sampled_at_utc.replace(tzinfo=UTC)
            if sample.sampled_at_utc.tzinfo is None
            else sample.sampled_at_utc.astimezone(UTC)
        )
        minute = stamp.replace(second=0, microsecond=0)
        key = (sample.tag_key, minute)
        rank = (stamp, str(sample.tie_breaker).zfill(30))
        if key not in ranks or rank > ranks[key]:
            ranks[key] = rank
            chosen[key] = sample.value
    minute_grid = [start + timedelta(minutes=index) for index in range(lookback_minutes)]
    return {
        "clicked_utc": clicked,
        "lookback_minutes": lookback_minutes,
        "series": [
            {
                "tag_id": tag,
                "display_name": metadata[tag].display_name,
                "data_type": metadata[tag].data_kind,
                "raw_data_type": metadata[tag].raw_data_type,
                "units": metadata[tag].units,
                "points": [
                    {
                        "minute_utc": minute,
                        "value": chosen.get((tag, minute)),
                        "missing": (tag, minute) not in chosen or chosen.get((tag, minute)) is None,
                    }
                    for minute in minute_grid
                ],
            }
            for tag in requested
        ],
    }


@router.post("/live-sessions", status_code=201)
async def start_live(payload: LiveCreate, session: SessionDep) -> dict[str, object]:
    if not get_settings().enable_live_mode:
        raise HTTPException(404, "Live mode is disabled")
    machine = session.get(MachineModel, payload.machine_id)
    version = session.get(RuleVersionModel, payload.rule_version_id)
    if (
        machine is None
        or not machine.enabled
        or version is None
        or version.status != "LOCKED"
        or version.rule_set.machine_id != machine.id
        or version.rule_set.archived
    ):
        raise HTTPException(422, "Live mode requires a valid machine and saved rule version")
    now = utc_now().replace(second=0, microsecond=0)
    analysis = AnalysisModel(
        machine_id=machine.id,
        rule_version_id=version.id,
        selected_start_utc=now,
        selected_end_utc=now,
        end_exclusive_utc=now + timedelta(minutes=1),
        mode="LIVE",
        status="ACTIVE",
    )
    session.add(analysis)
    session.flush()
    live = LiveSessionModel(
        machine_id=machine.id,
        rule_version_id=version.id,
        analysis_id=analysis.id,
        finalization_lag_minutes=payload.finalization_lag_minutes,
    )
    session.add(live)
    session.commit()
    return {"id": live.id, "analysis_id": analysis.id, "state": live.state, "auto_follow": True}


@router.get("/live-sessions/{live_id}")
async def live_status(live_id: int, session: SessionDep) -> dict[str, object]:
    live = session.get(LiveSessionModel, live_id)
    if live is None:
        raise HTTPException(404, "Live session not found")
    stale = live.worker_heartbeat_at is None or as_utc(
        live.worker_heartbeat_at
    ) < utc_now() - timedelta(minutes=3)
    return {
        "id": live.id,
        "analysis_id": live.analysis_id,
        "state": live.state,
        "last_finalized_minute": live.last_finalized_minute,
        "worker_heartbeat_at": live.worker_heartbeat_at,
        "worker_stale": stale,
        "timeline_url": f"/api/analyses/{live.analysis_id}/timeline",
    }


@router.get("/live-sessions/{live_id}/latest")
async def live_latest(live_id: int, session: SessionDep) -> dict[str, object]:
    live = session.get(LiveSessionModel, live_id)
    if live is None:
        raise HTTPException(404, "Live session not found")
    definition = version_to_domain(live.analysis.rule_version)
    tag_kinds = {
        condition.tag_key: condition.data_type.value for condition in definition.conditions
    }
    now = utc_now()
    latest: dict[str, dict[str, object]] = {}
    latest_stamps: dict[str, datetime] = {}
    for sample in get_source_repository().get_samples(
        live.analysis.machine.source_key,
        tag_kinds,
        now - timedelta(minutes=5),
        now + timedelta(minutes=1),
    ):
        stamp = (
            sample.sampled_at_utc.replace(tzinfo=UTC)
            if sample.sampled_at_utc.tzinfo is None
            else sample.sampled_at_utc.astimezone(UTC)
        )
        if sample.tag_key not in latest_stamps or stamp > latest_stamps[sample.tag_key]:
            latest_stamps[sample.tag_key] = stamp
            latest[sample.tag_key] = {
                "tag_id": sample.tag_key,
                "value": sample.value,
                "sampled_at_utc": stamp,
            }
    return {"observed_at_utc": now, "values": list(latest.values())}


@router.post("/live-sessions/{live_id}/stop")
async def stop_live(live_id: int, session: SessionDep) -> dict[str, object]:
    live = session.get(LiveSessionModel, live_id)
    if live is None:
        raise HTTPException(404, "Live session not found")
    live.state = "STOPPED"
    live.stopped_at = utc_now()
    live.analysis.status = "STOPPED"
    session.commit()
    return {"id": live.id, "state": live.state}


@router.post("/live-sessions/{live_id}/repair")
async def repair_live(live_id: int, session: SessionDep) -> dict[str, object]:
    """Explicitly request a bounded live-window recomputation."""
    live = session.get(LiveSessionModel, live_id)
    if live is None:
        raise HTTPException(404, "Live session not found")
    if live.state != "ACTIVE" or live.last_finalized_minute is None:
        raise HTTPException(422, "Only an active finalized live session can be repaired")
    definition = version_to_domain(live.analysis.rule_version)
    rewind_to = as_utc(live.last_finalized_minute) - timedelta(
        minutes=definition.preload_minutes + 1
    )
    live.last_finalized_minute = max(as_utc(live.analysis.selected_start_utc), rewind_to)
    session.commit()
    return {
        "id": live.id,
        "state": live.state,
        "repair_from_utc": live.last_finalized_minute,
    }


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        dispose_source_repository()

    app = FastAPI(title="RecipeControl API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def correlation(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_complete request_id=%s method=%s path=%s status=%s elapsed_ms=%.2f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - started) * 1000,
        )
        return response

    app.include_router(router)
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return app


app = create_app()
