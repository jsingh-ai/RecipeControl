import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from recipecontrol.database import SessionLocal, utc_now
from recipecontrol.live_worker import process_live_once
from recipecontrol.models import (
    AnalysisJobModel,
    AnalysisMinuteModel,
    AnalysisModel,
    ClassificationModel,
    SegmentModel,
)
from recipecontrol.source.base import Machine, Sample, Tag, TagPage
from recipecontrol.source.fixture import FixtureSourceDataRepository
from recipecontrol.worker import (
    HeartbeatError,
    background_heartbeat,
    claim_one,
    process_job,
    recover_stale_jobs,
    run_once,
    touch_heartbeat,
)


def saved_rule(client: TestClient) -> tuple[int, int]:
    machine = client.get("/api/machines").json()[0]
    created = client.post(
        "/api/rule-sets", json={"machine_id": machine["id"], "name": "Web speed breaks"}
    ).json()
    version_id = created["version"]["id"]
    payload = {
        "root_operator": "OR",
        "groups": [
            {
                "internal_operator": "OR",
                "conditions": [
                    {
                        "source_tag_key": "temperature",
                        "source_display_name": "Temperature",
                        "source_data_type": "numeric",
                        "operator": "ABOVE_MAXIMUM",
                        "maximum": "250",
                        "duration_minutes": 5,
                    },
                    {
                        "source_tag_key": "speed",
                        "source_display_name": "Speed",
                        "source_data_type": "numeric",
                        "operator": "INCREASE_BY",
                        "delta_amount": "25",
                        "delta_window_minutes": 5,
                        "duration_minutes": 0,
                    },
                ],
            }
        ],
    }
    assert client.put(f"/api/rule-versions/{version_id}", json=payload).status_code == 200
    assert client.post(f"/api/rule-versions/{version_id}/lock").status_code == 200
    return machine["id"], version_id


def create_analysis(client: TestClient, machine_id: int, version_id: int, **extra):
    payload = {
        "machine_id": machine_id,
        "rule_version_id": version_id,
        "selected_start_utc": "2026-06-11T19:50:00Z",
        "selected_end_utc": "2026-06-11T20:50:00Z",
        **extra,
    }
    return client.post("/api/analyses", json=payload)


class MutableMetadataSource(FixtureSourceDataRepository):
    def __init__(self) -> None:
        self.tags = {
            "temperature": Tag(
                "temperature", "m1", "Authoritative Temperature", "Double", "numeric"
            ),
            "other": Tag("other", "m2", "Other Machine Tag", "Double", "numeric"),
            "disabled": Tag("disabled", "m1", "Disabled Tag", "Double", "numeric"),
        }

    def list_machines(self):
        return (Machine("m1", "Machine One"), Machine("m2", "Machine Two"))

    def search_tags(self, machine_key: str, query: str = "", *, limit: int = 50, offset: int = 0):
        matches = tuple(
            tag
            for key, tag in self.tags.items()
            if key != "disabled"
            and tag.machine_key == machine_key
            and query.casefold() in tag.display_name.casefold()
        )
        return TagPage(
            matches[offset : offset + limit], limit, offset, len(matches) > offset + limit
        )

    def resolve_tags(self, machine_key: str, tag_keys, *, include_disabled: bool = False):
        return tuple(
            tag
            for key in tag_keys
            if (tag := self.tags.get(key)) is not None
            and tag.machine_key == machine_key
            and (include_disabled or key != "disabled")
        )

    def get_samples(self, machine_key, tag_kinds, start_utc, end_utc):
        if machine_key != "m1":
            return
        row_id = 1
        minute = start_utc
        while minute < end_utc:
            for key in tag_kinds:
                yield Sample(key, minute + timedelta(seconds=5), Decimal("260"), row_id)
                row_id += 1
            minute += timedelta(minutes=1)


def test_rule_save_uses_authoritative_tag_metadata_and_keeps_locked_snapshot(
    client: TestClient, monkeypatch
) -> None:
    source = MutableMetadataSource()
    monkeypatch.setattr("recipecontrol.api.get_source_repository", lambda: source)
    machine = client.get("/api/machines").json()[0]
    created = client.post(
        "/api/rule-sets", json={"machine_id": machine["id"], "name": "Trusted metadata"}
    ).json()
    version_id = created["version"]["id"]
    payload = {
        "root_operator": "OR",
        "groups": [
            {
                "internal_operator": "OR",
                "conditions": [
                    {
                        "tag_id": "temperature",
                        "source_display_name": "Spoofed",
                        "source_data_type": "text",
                        "operator": "ABOVE_MAXIMUM",
                        "maximum": "250",
                    }
                ],
            }
        ],
    }
    saved = client.put(f"/api/rule-versions/{version_id}", json=payload)
    assert saved.status_code == 200
    condition = saved.json()["groups"][0]["conditions"][0]
    assert condition["source_display_name"] == "Authoritative Temperature"
    assert condition["source_raw_data_type"] == "Double"
    assert condition["source_data_type"] == "numeric"
    assert client.post(f"/api/rule-versions/{version_id}/lock").status_code == 200
    source.tags["temperature"] = Tag("temperature", "m1", "Renamed Later", "Float", "numeric")
    locked = client.get(f"/api/rule-versions/{version_id}").json()
    assert locked["groups"][0]["conditions"][0]["source_display_name"] == (
        "Authoritative Temperature"
    )


@pytest.mark.parametrize("tag_id", ["other", "missing", "disabled"])
def test_invalid_cross_machine_nonexistent_and_disabled_tags_are_rejected(
    client: TestClient, monkeypatch, tag_id: str
) -> None:
    source = MutableMetadataSource()
    monkeypatch.setattr("recipecontrol.api.get_source_repository", lambda: source)
    machine = client.get("/api/machines").json()[0]
    version_id = client.post(
        "/api/rule-sets", json={"machine_id": machine["id"], "name": f"Invalid {tag_id}"}
    ).json()["version"]["id"]
    response = client.put(
        f"/api/rule-versions/{version_id}",
        json={
            "root_operator": "OR",
            "groups": [
                {
                    "internal_operator": "OR",
                    "conditions": [
                        {"tag_id": tag_id, "operator": "EQUALS", "comparison_value": "x"}
                    ],
                }
            ],
        },
    )
    assert response.status_code == 422


def test_one_condition_is_enough_and_locked_version_is_immutable(client: TestClient) -> None:
    machine = client.get("/api/machines").json()[0]
    created = client.post(
        "/api/rule-sets", json={"machine_id": machine["id"], "name": "Temperature"}
    ).json()
    version_id = created["version"]["id"]
    payload = {
        "root_operator": "OR",
        "groups": [
            {
                "internal_operator": "OR",
                "conditions": [
                    {
                        "source_tag_key": "temperature",
                        "source_display_name": "Temperature",
                        "source_data_type": "numeric",
                        "operator": "ABOVE_MAXIMUM",
                        "maximum": "250",
                        "duration_minutes": 0,
                    }
                ],
            }
        ],
    }
    assert client.put(f"/api/rule-versions/{version_id}", json=payload).status_code == 200
    assert client.post(f"/api/rule-versions/{version_id}/lock").status_code == 200
    assert client.put(f"/api/rule-versions/{version_id}", json=payload).status_code == 422


def test_same_source_tag_can_be_used_by_distinct_conditions(client: TestClient) -> None:
    machine = client.get("/api/machines").json()[0]
    version_id = client.post(
        "/api/rule-sets", json={"machine_id": machine["id"], "name": "Repeated temperature"}
    ).json()["version"]["id"]
    response = client.put(
        f"/api/rule-versions/{version_id}",
        json={
            "root_operator": "OR",
            "groups": [
                {
                    "internal_operator": "OR",
                    "conditions": [
                        {
                            "tag_id": "temperature",
                            "operator": "ABOVE_MAXIMUM",
                            "maximum": "250",
                            "duration_minutes": 5,
                        },
                        {
                            "tag_id": "temperature",
                            "operator": "INCREASE_BY",
                            "delta_amount": "5",
                            "delta_window_minutes": 10,
                        },
                    ],
                }
            ],
        },
    )
    assert response.status_code == 200
    conditions = response.json()["groups"][0]["conditions"]
    assert [item["source_tag_key"] for item in conditions] == ["temperature", "temperature"]
    assert conditions[0]["id"] != conditions[1]["id"]


def test_new_version_is_completely_blank(client: TestClient) -> None:
    _, version_id = saved_rule(client)
    version = client.get(f"/api/rule-versions/{version_id}").json()
    new_version = client.post(f"/api/rule-sets/{version['rule_set_id']}/versions").json()
    assert new_version["version_number"] == 2
    assert new_version["status"] == "DRAFT"
    assert new_version["groups"] == []
    with SessionLocal() as session:
        assert (
            session.scalar(
                select(func.count(ClassificationModel.id)).where(
                    ClassificationModel.rule_version_id == new_version["id"]
                )
            )
            == 0
        )


def test_duplicate_conflict_and_explicit_creation(client: TestClient) -> None:
    machine_id, version_id = saved_rule(client)
    first = create_analysis(client, machine_id, version_id)
    assert first.status_code == 202
    conflict = create_analysis(client, machine_id, version_id)
    assert conflict.status_code == 409
    assert (
        conflict.json()["message"] == "An analysis already exists for this definition and period."
    )
    duplicate = create_analysis(client, machine_id, version_id, create_duplicate=True)
    assert duplicate.status_code == 202
    assert duplicate.json()["duplicate_of_analysis_id"] == first.json()["id"]


def test_duplicate_results_prefer_newest_complete_analysis(client: TestClient) -> None:
    machine_id, version_id = saved_rule(client)
    failed_id = create_analysis(client, machine_id, version_id).json()["id"]
    older_complete_id = create_analysis(
        client, machine_id, version_id, create_duplicate=True
    ).json()["id"]
    newest_complete_id = create_analysis(
        client, machine_id, version_id, create_duplicate=True
    ).json()["id"]
    with SessionLocal() as session:
        failed = session.get(AnalysisModel, failed_id)
        older = session.get(AnalysisModel, older_complete_id)
        newest = session.get(AnalysisModel, newest_complete_id)
        assert failed and older and newest
        failed.status = "FAILED"
        older.status = "COMPLETE"
        older.completed_at = utc_now() - timedelta(minutes=2)
        newest.status = "COMPLETE"
        newest.completed_at = utc_now() - timedelta(minutes=1)
        session.commit()
    conflict = create_analysis(client, machine_id, version_id).json()
    assert [item["id"] for item in conflict["matches"]] == [
        newest_complete_id,
        older_complete_id,
        failed_id,
    ]


def test_worker_timeline_label_classification_and_snapshot(client: TestClient) -> None:
    machine_id, version_id = saved_rule(client)
    analysis_id = create_analysis(client, machine_id, version_id).json()["id"]
    assert run_once("pytest-worker")
    analysis = client.get(f"/api/analyses/{analysis_id}").json()
    assert analysis["status"] == "COMPLETE"
    timeline = client.get(f"/api/analyses/{analysis_id}/timeline").json()
    assert timeline["segments"]
    assert timeline["segments"][0]["start_utc"].startswith("2026-06-11T19:50")
    assert timeline["segments"][-1]["end_utc"].startswith("2026-06-11T20:51")
    classification = client.post(
        f"/api/rule-versions/{version_id}/classifications", json={"name": "Roll Change"}
    ).json()
    segment = next(item for item in timeline["segments"] if item["system_state"] == "BREAK")
    updated = client.patch(
        f"/api/analyses/{analysis_id}/segments/{segment['id']}",
        json={
            "quality_label": "BAD",
            "classification_id": classification["id"],
            "note": "Observed stop\nConfirmed by operator",
        },
    ).json()
    assert updated["training_eligible"] is True
    assert updated["classification_name"] == "Roll Change"
    assert client.delete(f"/api/classifications/{classification['id']}").status_code == 200
    assert client.get(f"/api/rule-versions/{version_id}/classifications").json() == []
    reloaded = client.get(f"/api/segments/{segment['id']}").json()
    assert reloaded["classification_name"] == "Roll Change"


def test_retired_classification_is_preserved_only_on_its_existing_segment(
    client: TestClient,
) -> None:
    machine_id, version_id = saved_rule(client)
    first_id = create_analysis(client, machine_id, version_id).json()["id"]
    second_id = create_analysis(client, machine_id, version_id, create_duplicate=True).json()["id"]
    assert run_once("retired-classification-first")
    assert run_once("retired-classification-second")
    first_segment = client.get(f"/api/analyses/{first_id}/timeline").json()["segments"][0]
    second_segment = client.get(f"/api/analyses/{second_id}/timeline").json()["segments"][0]
    classification = client.post(
        f"/api/rule-versions/{version_id}/classifications",
        json={"name": "Retired existing annotation"},
    ).json()
    assigned = client.patch(
        f"/api/analyses/{first_id}/segments/{first_segment['id']}",
        json={"quality_label": "GOOD", "classification_id": classification["id"]},
    )
    assert assigned.status_code == 200
    assert client.delete(f"/api/classifications/{classification['id']}").status_code == 200

    preserved = client.patch(
        f"/api/analyses/{first_id}/segments/{first_segment['id']}",
        json={
            "quality_label": "UNSURE",
            "classification_id": classification["id"],
            "note": "Quality and note changed after retirement",
        },
    )
    assert preserved.status_code == 200
    assert preserved.json()["classification_name"] == "Retired existing annotation"
    rejected = client.patch(
        f"/api/analyses/{second_id}/segments/{second_segment['id']}",
        json={"classification_id": classification["id"]},
    )
    assert rejected.status_code == 422
    cleared = client.patch(
        f"/api/analyses/{first_id}/segments/{first_segment['id']}",
        json={"classification_id": None, "note": "Classification cleared"},
    )
    assert cleared.status_code == 200
    assert cleared.json()["classification_id"] is None


def test_system_segments_can_be_labeled_but_are_not_training_eligible(client: TestClient) -> None:
    machine_id, version_id = saved_rule(client)
    analysis_id = create_analysis(client, machine_id, version_id).json()["id"]
    assert run_once("pytest-worker")
    timeline = client.get(f"/api/analyses/{analysis_id}/timeline").json()
    system_segment = next(
        item
        for item in timeline["segments"]
        if item["system_state"] in {"DATA_GAP", "INSUFFICIENT_HISTORY"}
    )
    updated = client.patch(
        f"/api/analyses/{analysis_id}/segments/{system_segment['id']}",
        json={"quality_label": "GOOD", "note": "known"},
    ).json()
    assert updated["quality_label"] == "GOOD"
    assert updated["training_eligible"] is False


def test_trend_defaults_to_condition_tags_and_fifteen_minutes(client: TestClient) -> None:
    machine_id, version_id = saved_rule(client)
    analysis_id = create_analysis(client, machine_id, version_id).json()["id"]
    assert run_once("pytest-worker")
    response = client.get(
        f"/api/analyses/{analysis_id}/trends",
        params={"clicked_utc": "2026-06-11T20:10:00Z"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["lookback_minutes"] == 15
    assert {series["tag_id"] for series in body["series"]} == {"temperature", "speed"}
    assert all(len(series["points"]) == 15 for series in body["series"])


def test_analysis_scoped_annotation_rejects_segment_from_another_analysis(
    client: TestClient,
) -> None:
    machine_id, version_id = saved_rule(client)
    first = create_analysis(client, machine_id, version_id).json()["id"]
    second = create_analysis(client, machine_id, version_id, create_duplicate=True).json()["id"]
    assert run_once("first-analysis")
    assert run_once("second-analysis")
    segment = client.get(f"/api/analyses/{first}/timeline").json()["segments"][0]
    response = client.patch(
        f"/api/analyses/{second}/segments/{segment['id']}",
        json={"quality_label": "BAD"},
    )
    assert response.status_code == 409
    assert client.get(f"/api/segments/{segment['id']}").json()["quality_label"] is None


def test_archived_definition_analysis_remains_inspectable_and_annotatable(
    client: TestClient,
) -> None:
    machine_id, version_id = saved_rule(client)
    analysis_id = create_analysis(client, machine_id, version_id).json()["id"]
    assert run_once("archive-worker")
    version = client.get(f"/api/rule-versions/{version_id}").json()
    assert client.post(f"/api/rule-sets/{version['rule_set_id']}/archive").status_code == 200
    assert client.get(f"/api/rule-versions/{version_id}").status_code == 200
    timeline = client.get(f"/api/analyses/{analysis_id}/timeline")
    assert timeline.status_code == 200 and timeline.json()["conditions"]
    segment = timeline.json()["segments"][0]
    updated = client.patch(
        f"/api/analyses/{analysis_id}/segments/{segment['id']}",
        json={"quality_label": "UNSURE", "note": "Historical review"},
    )
    assert updated.status_code == 200
    assert (
        client.get(
            f"/api/analyses/{analysis_id}/trends", params={"clicked_utc": segment["start_utc"]}
        ).status_code
        == 200
    )
    assert create_analysis(client, machine_id, version_id, create_duplicate=True).status_code == 422
    assert client.post(f"/api/rule-sets/{version['rule_set_id']}/versions").status_code == 422


def test_default_historical_trend_uses_snapshot_after_source_tag_is_disabled(
    client: TestClient, monkeypatch
) -> None:
    source = MutableMetadataSource()
    monkeypatch.setattr("recipecontrol.api.get_source_repository", lambda: source)
    monkeypatch.setattr("recipecontrol.worker.get_source_repository", lambda: source)
    machine = client.get("/api/machines").json()[0]
    version_id = client.post(
        "/api/rule-sets", json={"machine_id": machine["id"], "name": "Disabled later"}
    ).json()["version"]["id"]
    payload = {
        "root_operator": "OR",
        "groups": [
            {
                "internal_operator": "OR",
                "conditions": [
                    {
                        "tag_id": "temperature",
                        "operator": "ABOVE_MAXIMUM",
                        "maximum": "250",
                    }
                ],
            }
        ],
    }
    assert client.put(f"/api/rule-versions/{version_id}", json=payload).status_code == 200
    assert client.post(f"/api/rule-versions/{version_id}/lock").status_code == 200
    analysis_id = create_analysis(client, machine["id"], version_id).json()["id"]
    assert run_once("disabled-tag-worker")
    source.tags["disabled"] = source.tags.pop("temperature")
    response = client.get(
        f"/api/analyses/{analysis_id}/trends",
        params={"clicked_utc": "2026-06-11T20:10:00Z"},
    )
    assert response.status_code == 200
    series = response.json()["series"][0]
    assert series["tag_id"] == "temperature"
    assert series["display_name"] == "Authoritative Temperature"


def test_failed_job_has_no_partial_output(client: TestClient, monkeypatch) -> None:
    machine_id, version_id = saved_rule(client)
    analysis_id = create_analysis(client, machine_id, version_id).json()["id"]
    with SessionLocal() as session:
        job = session.scalar(
            select(AnalysisJobModel).where(AnalysisJobModel.analysis_id == analysis_id)
        )
        assert job is not None
        job.state = "RUNNING"
        job.attempt_count = 3
        session.commit()
        job_id = job.id

    class FailingSource:
        def get_samples(self, *args, **kwargs):
            raise RuntimeError("fixture failure")

    monkeypatch.setattr("recipecontrol.worker.get_source_repository", lambda: FailingSource())
    process_job(job_id)
    with SessionLocal() as session:
        analysis = session.get(AnalysisModel, analysis_id)
        assert analysis is not None and analysis.status == "FAILED"
        assert (
            session.scalar(
                select(func.count(SegmentModel.id)).where(SegmentModel.analysis_id == analysis_id)
            )
            == 0
        )


def test_sqlite_worker_persists_more_than_one_minute_batch(client: TestClient) -> None:
    machine_id, version_id = saved_rule(client)
    analysis_id = create_analysis(
        client,
        machine_id,
        version_id,
        selected_end_utc="2026-06-12T12:30:00Z",
    ).json()["id"]
    assert run_once("sqlite-1001-minute-worker")
    with SessionLocal() as session:
        analysis = session.get(AnalysisModel, analysis_id)
        assert analysis is not None and analysis.status == "COMPLETE"
        assert (
            session.scalar(
                select(func.count(AnalysisMinuteModel.id)).where(
                    AnalysisMinuteModel.analysis_id == analysis_id
                )
            )
            == 1001
        )


def test_sqlite_worker_completes_full_16951_minute_preset(client: TestClient) -> None:
    machine_id, version_id = saved_rule(client)
    analysis_id = create_analysis(
        client,
        machine_id,
        version_id,
        selected_end_utc="2026-06-23T14:20:00Z",
    ).json()["id"]
    assert run_once("sqlite-full-preset-worker")
    with SessionLocal() as session:
        analysis = session.get(AnalysisModel, analysis_id)
        assert analysis is not None and analysis.status == "COMPLETE"
        assert (
            session.scalar(
                select(func.count(AnalysisMinuteModel.id)).where(
                    AnalysisMinuteModel.analysis_id == analysis_id
                )
            )
            == 16_951
        )
    segments = client.get(f"/api/analyses/{analysis_id}/timeline").json()["segments"]
    assert segments[0]["start_utc"].startswith("2026-06-11T19:50")
    assert segments[-1]["end_utc"].startswith("2026-06-23T14:21")
    assert all(
        left["end_utc"] == right["start_utc"]
        for left, right in zip(segments, segments[1:], strict=False)
    )


def test_background_heartbeat_failure_is_propagated(monkeypatch) -> None:
    def fail(_job_id: int) -> None:
        raise RuntimeError("heartbeat database unavailable")

    monkeypatch.setattr("recipecontrol.worker.touch_heartbeat", fail)
    with (
        pytest.raises(HeartbeatError, match="heartbeat failed"),
        background_heartbeat(123, interval_seconds=0.01),
    ):
        time.sleep(0.03)


def test_heartbeat_rejects_a_replaced_worker_owner(client: TestClient) -> None:
    machine_id, version_id = saved_rule(client)
    analysis_id = create_analysis(client, machine_id, version_id).json()["id"]
    with SessionLocal() as session:
        job = session.scalar(
            select(AnalysisJobModel).where(AnalysisJobModel.analysis_id == analysis_id)
        )
        assert job is not None
        job.state = "RUNNING"
        job.claimed_by = "replacement-worker"
        job.heartbeat_at = utc_now()
        session.commit()
        job_id = job.id

    with pytest.raises(HeartbeatError, match="no longer owns"):
        touch_heartbeat(job_id, "stale-worker")


def test_stale_job_is_reclaimed_then_fails_at_retry_limit(client: TestClient) -> None:
    machine_id, version_id = saved_rule(client)
    analysis_id = create_analysis(client, machine_id, version_id).json()["id"]
    with SessionLocal() as session:
        job = session.scalar(
            select(AnalysisJobModel).where(AnalysisJobModel.analysis_id == analysis_id)
        )
        assert job is not None
        job.state = "RUNNING"
        job.attempt_count = 1
        job.heartbeat_at = utc_now() - timedelta(hours=1)
        job.persistence_lease_until = utc_now() + timedelta(minutes=5)
        session.commit()
        assert recover_stale_jobs(session) == 0
        job.persistence_lease_until = utc_now() - timedelta(seconds=1)
        session.commit()
        assert recover_stale_jobs(session) == 1
        assert job.state == "QUEUED"
        job.state = "RUNNING"
        job.attempt_count = 3
        job.heartbeat_at = utc_now() - timedelta(hours=1)
        session.commit()
        assert recover_stale_jobs(session) == 1
        assert job.state == "FAILED"
        assert session.get(AnalysisModel, analysis_id).error_message == (
            "Analysis worker stopped before completion. Retry limit reached."
        )


def test_concurrent_claim_attempt_cannot_claim_one_job_twice(client: TestClient) -> None:
    machine_id, version_id = saved_rule(client)
    create_analysis(client, machine_id, version_id)
    with SessionLocal() as first, SessionLocal() as second:
        claimed = claim_one(first, "worker-one")
        assert claimed is not None
        assert claim_one(second, "worker-two") is None


def test_exact_minute_endpoint_returns_interior_values(client: TestClient) -> None:
    machine_id, version_id = saved_rule(client)
    analysis_id = create_analysis(client, machine_id, version_id).json()["id"]
    assert run_once("minute-worker")
    clicked = datetime(2026, 6, 11, 20, 10, tzinfo=UTC)
    body = client.get(f"/api/analyses/{analysis_id}/minutes/{clicked.isoformat()}").json()
    expected_speed = str(int(clicked.timestamp() // 60) % 60 * 5)
    speed = next(item for item in body["conditions"].values() if item["tag_id"] == "speed")
    assert body["minute_utc"].startswith("2026-06-11T20:10")
    assert speed["value"] == expected_speed
    assert "pending_progress" in speed
    assert "root_expression_result" in body


def test_source_repository_exposes_no_write_operation() -> None:
    from recipecontrol.source.fixture import FixtureSourceDataRepository

    source = FixtureSourceDataRepository()
    assert not any(hasattr(source, name) for name in ("add", "update", "delete", "execute"))


def test_source_diagnostics_aggregate_distinct_raw_types() -> None:
    from recipecontrol.source.fixture import FixtureSourceDataRepository

    diagnostics = FixtureSourceDataRepository().diagnostics()
    rows = diagnostics["data_types"]
    assert len([row for row in rows if row["raw_data_type"] == "Double"]) == 1
    assert next(row for row in rows if row["raw_data_type"] == "Double")["count"] == 3


def test_live_worker_finalizes_marks_active_repairs_and_stops(
    client: TestClient, monkeypatch
) -> None:
    from recipecontrol.config import get_settings

    enabled = get_settings().model_copy(update={"enable_live_mode": True})
    monkeypatch.setattr("recipecontrol.api.get_settings", lambda: enabled)
    machine_id, version_id = saved_rule(client)
    created = client.post(
        "/api/live-sessions",
        json={
            "machine_id": machine_id,
            "rule_version_id": version_id,
            "finalization_lag_minutes": 0,
        },
    )
    assert created.status_code == 201
    live_id = created.json()["id"]
    with SessionLocal() as session:
        analysis = session.get(AnalysisModel, created.json()["analysis_id"])
        assert analysis is not None
        start = analysis.selected_start_utc.replace(tzinfo=UTC)
    assert process_live_once(start + timedelta(minutes=2)) == 1
    assert process_live_once(start + timedelta(minutes=3)) == 1
    timeline = client.get(f"/api/analyses/{created.json()['analysis_id']}/timeline").json()
    assert timeline["segments"][-1]["active_live"] is True
    assert all(
        (left["system_state"], left["contributing_condition_ids"])
        != (right["system_state"], right["contributing_condition_ids"])
        for left, right in zip(timeline["segments"], timeline["segments"][1:], strict=False)
    )
    status = client.get(f"/api/live-sessions/{live_id}").json()
    assert status["worker_stale"] is False
    assert client.post(f"/api/live-sessions/{live_id}/repair").status_code == 200
    assert process_live_once(start + timedelta(minutes=3)) == 1
    stopped = client.post(f"/api/live-sessions/{live_id}/stop").json()
    assert stopped["state"] == "STOPPED"


def test_machine_catalog_disables_removed_and_reenables_returned_source_machine(
    client: TestClient, monkeypatch
) -> None:
    source = MutableMetadataSource()
    visible = [Machine("m1", "Machine One"), Machine("m2", "Machine Two")]
    monkeypatch.setattr(source, "list_machines", lambda: tuple(visible))
    monkeypatch.setattr("recipecontrol.api.get_source_repository", lambda: source)
    first = client.get("/api/machines").json()
    machine_two = next(item for item in first if item["source_key"] == "m2")
    visible[:] = [Machine("m1", "Machine One")]
    assert {item["source_key"] for item in client.get("/api/machines").json()} == {"m1"}
    inactive = client.get("/api/machines", params={"include_inactive": "true"}).json()
    assert next(item for item in inactive if item["id"] == machine_two["id"])["enabled"] is False
    assert (
        client.post(
            "/api/rule-sets", json={"machine_id": machine_two["id"], "name": "Not allowed"}
        ).status_code
        == 422
    )
    visible.append(Machine("m2", "Machine Two Restored"))
    restored = client.get("/api/machines").json()
    assert next(item for item in restored if item["id"] == machine_two["id"])["enabled"] is True


def test_inactive_machine_history_remains_available_when_source_sync_fails(
    client: TestClient, monkeypatch
) -> None:
    machine_id, version_id = saved_rule(client)
    analysis_id = create_analysis(client, machine_id, version_id).json()["id"]
    assert run_once("inactive-history-worker")

    source = FixtureSourceDataRepository()
    monkeypatch.setattr(source, "list_machines", lambda: ())
    monkeypatch.setattr("recipecontrol.api.get_source_repository", lambda: source)
    inactive_catalog = client.get("/api/machine-catalog").json()
    inactive = next(item for item in inactive_catalog["items"] if item["id"] == machine_id)
    assert inactive["enabled"] is False

    def unavailable():
        raise RuntimeError("collector temporarily unavailable")

    monkeypatch.setattr(source, "list_machines", unavailable)
    stale_catalog = client.get("/api/machine-catalog")
    assert stale_catalog.status_code == 200
    assert stale_catalog.json()["source_sync_warning"]
    assert (
        next(item for item in stale_catalog.json()["items"] if item["id"] == machine_id)["enabled"]
        is False
    )
    assert client.get(f"/api/analyses?machine_id={machine_id}").status_code == 200
    timeline = client.get(f"/api/analyses/{analysis_id}/timeline")
    assert timeline.status_code == 200
    segment = timeline.json()["segments"][0]
    assert (
        client.get(f"/api/analyses/{analysis_id}/minutes/{segment['start_utc']}").status_code == 200
    )
    assert (
        client.patch(
            f"/api/analyses/{analysis_id}/segments/{segment['id']}",
            json={"quality_label": "GOOD", "note": "Reviewed while source offline"},
        ).status_code
        == 200
    )
    assert create_analysis(client, machine_id, version_id, create_duplicate=True).status_code == 422
    assert (
        client.post(
            "/api/rule-sets", json={"machine_id": machine_id, "name": "Inactive blocked"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/live-sessions",
            json={"machine_id": machine_id, "rule_version_id": version_id},
        ).status_code
        == 404
    )


def test_blank_names_and_invalid_analysis_range_are_rejected(client: TestClient) -> None:
    machine = client.get("/api/machines").json()[0]
    assert (
        client.post("/api/rule-sets", json={"machine_id": machine["id"], "name": "   "}).status_code
        == 422
    )
    machine_id, version_id = saved_rule(client)
    assert (
        client.post(
            f"/api/rule-versions/{version_id}/classifications", json={"name": "   "}
        ).status_code
        == 422
    )
    assert (
        create_analysis(
            client,
            machine_id,
            version_id,
            selected_start_utc="2026-06-12T00:00:00Z",
            selected_end_utc="2026-06-11T00:00:00Z",
        ).status_code
        == 422
    )
