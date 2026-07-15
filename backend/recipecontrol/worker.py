import argparse
import hashlib
import logging
import os
import socket
import time
from collections.abc import Iterable, Iterator
from datetime import timedelta

from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from recipecontrol.config import get_settings
from recipecontrol.database import SessionLocal, as_utc, utc_now
from recipecontrol.domain.engine import segment_timeline
from recipecontrol.models import (
    AnalysisJobModel,
    AnalysisMinuteModel,
    AnalysisModel,
    BoundaryEventModel,
    ConditionIntervalModel,
    SegmentModel,
)
from recipecontrol.services import version_to_domain
from recipecontrol.source import get_source_repository
from recipecontrol.source.base import Sample

logger = logging.getLogger("recipecontrol.worker")


def recover_stale_jobs(session: Session) -> int:
    settings = get_settings()
    cutoff = utc_now() - timedelta(seconds=settings.stale_job_timeout_seconds)
    stale = list(
        session.scalars(
            select(AnalysisJobModel).where(
                AnalysisJobModel.state == "RUNNING",
                AnalysisJobModel.heartbeat_at < cutoff,
            )
        )
    )
    now = utc_now()
    for job in stale:
        analysis = session.get(AnalysisModel, job.analysis_id)
        if job.attempt_count < settings.historical_job_max_attempts:
            job.state = "QUEUED"
            job.claimed_by = None
            job.claimed_at = None
            job.heartbeat_at = None
            job.error_details = "stale_worker_reclaimed"
            if analysis is not None:
                analysis.status = "QUEUED"
                analysis.error_message = None
        else:
            job.state = "FAILED"
            job.finished_at = now
            job.error_details = "stale_worker_retry_limit"
            if analysis is not None:
                analysis.status = "FAILED"
                analysis.completed_at = now
                analysis.error_message = (
                    "Analysis worker stopped before completion. Retry limit reached."
                )
    if stale:
        session.commit()
    return len(stale)


def heartbeating_samples(samples: Iterable[Sample], job_id: int) -> Iterator[Sample]:
    next_heartbeat = time.monotonic() + 10
    for sample in samples:
        if time.monotonic() >= next_heartbeat:
            with SessionLocal() as heartbeat_session:
                heartbeat_session.execute(
                    update(AnalysisJobModel)
                    .where(AnalysisJobModel.id == job_id, AnalysisJobModel.state == "RUNNING")
                    .values(heartbeat_at=utc_now())
                )
                heartbeat_session.commit()
            next_heartbeat = time.monotonic() + 10
        yield sample


def claim_one(session: Session, worker_id: str) -> int | None:
    candidate = session.scalar(
        select(AnalysisJobModel.id)
        .where(AnalysisJobModel.state == "QUEUED")
        .order_by(AnalysisJobModel.created_at, AnalysisJobModel.id)
        .limit(1)
    )
    if candidate is None:
        return None
    now = utc_now()
    claimed = session.execute(
        update(AnalysisJobModel)
        .where(AnalysisJobModel.id == candidate, AnalysisJobModel.state == "QUEUED")
        .values(
            state="RUNNING",
            claimed_by=worker_id,
            claimed_at=now,
            heartbeat_at=now,
            attempt_count=AnalysisJobModel.attempt_count + 1,
        )
    )
    session.commit()
    return candidate if getattr(claimed, "rowcount", 0) == 1 else None


def process_job(job_id: int) -> None:
    source = get_source_repository()
    with SessionLocal() as session:
        job = session.get(AnalysisJobModel, job_id)
        if job is None:
            return
        analysis = session.get(AnalysisModel, job.analysis_id)
        if analysis is None:
            raise RuntimeError("Analysis job refers to a missing analysis")
        analysis.status = "RUNNING"
        analysis.started_at = utc_now()
        job.heartbeat_at = utc_now()
        session.commit()
        try:
            definition = version_to_domain(analysis.rule_version)
            tag_kinds = {
                condition.tag_key: condition.data_type.value for condition in definition.conditions
            }
            start = as_utc(analysis.selected_start_utc)
            selected_end = as_utc(analysis.selected_end_utc)
            preload_start = start - timedelta(minutes=definition.preload_minutes)
            generation_started = time.perf_counter()
            samples = source.get_samples(
                analysis.machine.source_key,
                tag_kinds,
                preload_start,
                selected_end + timedelta(minutes=1),
            )
            result = segment_timeline(
                definition, heartbeating_samples(samples, job_id), start, selected_end
            )

            # End the read transaction before atomically replacing generated output.
            session.commit()
            with session.begin():
                session.execute(
                    delete(BoundaryEventModel).where(BoundaryEventModel.analysis_id == analysis.id)
                )
                session.execute(
                    delete(AnalysisMinuteModel).where(
                        AnalysisMinuteModel.analysis_id == analysis.id
                    )
                )
                session.execute(
                    delete(ConditionIntervalModel).where(
                        ConditionIntervalModel.analysis_id == analysis.id
                    )
                )
                session.execute(delete(SegmentModel).where(SegmentModel.analysis_id == analysis.id))
                stored_segments: list[SegmentModel] = []
                for segment in result.segments:
                    identity_key = hashlib.sha256(
                        f"{analysis.id}|{segment.start_utc.isoformat()}|{segment.identity}".encode()
                    ).hexdigest()
                    stored = SegmentModel(
                        analysis_id=analysis.id,
                        start_utc=segment.start_utc,
                        end_utc=segment.end_utc,
                        system_state=segment.system_state.value,
                        contributing_condition_ids=list(segment.contributing_condition_ids),
                        identity_key=identity_key,
                    )
                    session.add(stored)
                    stored_segments.append(stored)
                session.flush()
                minute_rows: list[dict[str, object]] = []
                segment_index = 0
                for evaluation in result.minute_evaluations:
                    while evaluation.minute_utc >= stored_segments[segment_index].end_utc:
                        segment_index += 1
                    minute_rows.append(
                        {
                            "analysis_id": analysis.id,
                            "segment_id": stored_segments[segment_index].id,
                            "minute_utc": evaluation.minute_utc,
                            "system_state": evaluation.system_state.value,
                            "snapshot": evaluation.snapshot,
                        }
                    )
                    if len(minute_rows) == 1000:
                        session.execute(insert(AnalysisMinuteModel), minute_rows)
                        minute_rows.clear()
                if minute_rows:
                    session.execute(insert(AnalysisMinuteModel), minute_rows)
                for interval in result.condition_intervals:
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
                for boundary in result.boundaries:
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
                analysis.status = "COMPLETE"
                analysis.source_row_count = result.source_row_count
                analysis.reproducibility_metadata = {
                    "engine": "recipecontrol-0.1",
                    "preload_minutes": definition.preload_minutes,
                    "tag_keys": sorted(tag_kinds),
                }
                analysis.completed_at = utc_now()
                analysis.error_message = None
                job.state = "COMPLETE"
                job.heartbeat_at = utc_now()
                job.finished_at = utc_now()
                job.error_details = None
            logger.info(
                "analysis_complete job_id=%s analysis_id=%s rows=%s segments=%s elapsed_ms=%.2f",
                job.id,
                analysis.id,
                result.source_row_count,
                len(result.segments),
                (time.perf_counter() - generation_started) * 1000,
            )
        except Exception as error:
            session.rollback()
            logger.exception("analysis_failed analysis_id=%s", analysis.id)
            failed_job = session.get(AnalysisJobModel, job_id)
            failed_analysis = session.get(AnalysisModel, analysis.id)
            if failed_job and failed_analysis:
                settings = get_settings()
                failed_job.error_details = type(error).__name__
                if failed_job.attempt_count < settings.historical_job_max_attempts:
                    failed_job.state = "QUEUED"
                    failed_job.claimed_by = None
                    failed_job.claimed_at = None
                    failed_job.heartbeat_at = None
                    failed_analysis.status = "QUEUED"
                    failed_analysis.error_message = None
                else:
                    failed_job.state = "FAILED"
                    failed_job.finished_at = utc_now()
                    failed_analysis.status = "FAILED"
                    failed_analysis.error_message = "Analysis generation failed; see server logs."
                    failed_analysis.completed_at = utc_now()
                session.commit()


def run_once(worker_id: str | None = None) -> bool:
    identity = worker_id or f"{socket.gethostname()}-{os.getpid()}"
    with SessionLocal() as session:
        recover_stale_jobs(session)
        job_id = claim_one(session, identity)
    if job_id is None:
        return False
    process_job(job_id)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Process persisted RecipeControl analysis jobs")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if args.once:
        run_once()
        return
    while True:
        if not run_once():
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
