import argparse
import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from recipecontrol.database import SessionLocal, as_utc, utc_now
from recipecontrol.domain.engine import segment_timeline
from recipecontrol.models import (
    BoundaryEventModel,
    ConditionIntervalModel,
    LiveSessionModel,
    SegmentModel,
)
from recipecontrol.services import version_to_domain
from recipecontrol.source import get_source_repository

logger = logging.getLogger("recipecontrol.live_worker")


def process_live_once(now: datetime | None = None) -> int:
    source = get_source_repository()
    current = (now or utc_now()).astimezone(UTC).replace(second=0, microsecond=0)
    processed = 0
    with SessionLocal() as session:
        live_sessions = list(
            session.scalars(select(LiveSessionModel).where(LiveSessionModel.state == "ACTIVE"))
        )
        for live in live_sessions:
            live.worker_heartbeat_at = utc_now()
            target = current - timedelta(minutes=live.finalization_lag_minutes)
            analysis = live.analysis
            start = as_utc(analysis.selected_start_utc)
            if target < start or (
                live.last_finalized_minute is not None
                and target <= as_utc(live.last_finalized_minute)
            ):
                continue
            definition = version_to_domain(analysis.rule_version)
            last_finalized = (
                as_utc(live.last_finalized_minute) if live.last_finalized_minute else None
            )
            recompute_start = (
                start
                if last_finalized is None
                else max(
                    start,
                    last_finalized - timedelta(minutes=definition.preload_minutes),
                )
            )
            tag_keys = sorted({condition.tag_key for condition in definition.conditions})
            preload = recompute_start - timedelta(minutes=definition.preload_minutes)
            samples = source.get_samples(tag_keys, preload, target + timedelta(minutes=1))
            result = segment_timeline(definition, samples, recompute_start, target)
            affected_segments = list(
                session.scalars(
                    select(SegmentModel)
                    .where(
                        SegmentModel.analysis_id == analysis.id,
                        SegmentModel.end_utc >= recompute_start,
                    )
                    .order_by(SegmentModel.start_utc)
                )
            )
            existing = {
                (as_utc(item.start_utc), item.identity_key.split("|", 1)[-1]): item
                for item in affected_segments
            }
            predecessor = next(
                (
                    item
                    for item in affected_segments
                    if as_utc(item.start_utc) < recompute_start <= as_utc(item.end_utc)
                ),
                None,
            )
            if predecessor is not None and as_utc(predecessor.end_utc) > recompute_start:
                predecessor.end_utc = recompute_start
                predecessor.active_live = False
            session.execute(
                delete(BoundaryEventModel)
                .where(
                    BoundaryEventModel.analysis_id == analysis.id,
                    BoundaryEventModel.boundary_utc >= recompute_start,
                )
                .execution_options(synchronize_session=False)
            )
            affected_intervals = list(
                session.scalars(
                    select(ConditionIntervalModel).where(
                        ConditionIntervalModel.analysis_id == analysis.id,
                        ConditionIntervalModel.end_utc >= recompute_start,
                    )
                )
            )
            interval_predecessors: dict[int, ConditionIntervalModel] = {}
            for stored_interval in affected_intervals:
                if (
                    as_utc(stored_interval.start_utc)
                    < recompute_start
                    <= as_utc(stored_interval.end_utc)
                ):
                    if as_utc(stored_interval.end_utc) > recompute_start:
                        stored_interval.end_utc = recompute_start
                    interval_predecessors[stored_interval.condition_id] = stored_interval
            session.execute(
                delete(ConditionIntervalModel)
                .where(
                    ConditionIntervalModel.analysis_id == analysis.id,
                    ConditionIntervalModel.start_utc >= recompute_start,
                )
                .execution_options(synchronize_session=False)
            )
            for stored_interval in affected_intervals:
                if as_utc(stored_interval.start_utc) >= recompute_start:
                    session.expunge(stored_interval)
            session.execute(
                delete(SegmentModel)
                .where(
                    SegmentModel.analysis_id == analysis.id,
                    SegmentModel.start_utc >= recompute_start,
                )
                .execution_options(synchronize_session=False)
            )
            for stored_segment in affected_segments:
                if as_utc(stored_segment.start_utc) >= recompute_start:
                    session.expunge(stored_segment)
            for index, item in enumerate(result.segments):
                identity = item.identity
                prior = existing.get((item.start_utc, identity))
                if (
                    index == 0
                    and predecessor is not None
                    and predecessor.identity_key == f"live|{identity}"
                ):
                    predecessor.end_utc = item.end_utc
                    predecessor.active_live = len(result.segments) == 1
                    continue
                session.add(
                    SegmentModel(
                        analysis_id=analysis.id,
                        start_utc=item.start_utc,
                        end_utc=item.end_utc,
                        system_state=item.system_state.value,
                        contributing_condition_ids=list(item.contributing_condition_ids),
                        identity_key=f"live|{identity}",
                        quality_label=prior.quality_label if prior else None,
                        classification_id=prior.classification_id if prior else None,
                        classification_name_snapshot=(
                            prior.classification_name_snapshot if prior else None
                        ),
                        note=prior.note if prior else None,
                        label_updated_at=prior.label_updated_at if prior else None,
                        active_live=index == len(result.segments) - 1,
                    )
                )
            for interval in result.condition_intervals:
                interval_predecessor = interval_predecessors.get(interval.condition_id)
                if (
                    interval.start_utc == recompute_start
                    and interval_predecessor is not None
                    and interval_predecessor.state == interval.state.value
                ):
                    interval_predecessor.end_utc = interval.end_utc
                    continue
                session.add(
                    ConditionIntervalModel(
                        analysis_id=analysis.id,
                        condition_id=interval.condition_id,
                        start_utc=interval.start_utc,
                        end_utc=interval.end_utc,
                        state=interval.state.value,
                        trigger_utc=interval.trigger_utc,
                        confirmation_utc=interval.confirmation_utc,
                    )
                )
            for boundary_index, boundary in enumerate(result.boundaries):
                if (
                    boundary_index == 0
                    and predecessor is not None
                    and predecessor.identity_key == f"live|{boundary.next_identity}"
                ):
                    continue
                session.add(
                    BoundaryEventModel(
                        analysis_id=analysis.id,
                        boundary_utc=boundary.boundary_utc,
                        previous_identity=boundary.previous_identity,
                        next_identity=boundary.next_identity,
                        event_type=boundary.system_state.value,
                        explanation=boundary.explanation,
                        context=boundary.context,
                    )
                )
            live.last_finalized_minute = target
            analysis.selected_end_utc = target
            analysis.end_exclusive_utc = target + timedelta(minutes=1)
            analysis.source_row_count = result.source_row_count
            processed += 1
        session.commit()
    return processed


def main() -> None:
    parser = argparse.ArgumentParser(description="Process RecipeControl read-only live sessions")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.once:
        process_live_once()
        return
    while True:
        process_live_once()
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
