from datetime import UTC, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from recipecontrol.database import SessionLocal
from recipecontrol.live_worker import process_live_once
from recipecontrol.models import (
    AnalysisJobModel,
    AnalysisModel,
    ClassificationModel,
    SegmentModel,
)
from recipecontrol.worker import process_job, run_once


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
        f"/api/segments/{segment['id']}",
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
        f"/api/segments/{system_segment['id']}", json={"quality_label": "GOOD", "note": "known"}
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


def test_failed_job_has_no_partial_output(client: TestClient, monkeypatch) -> None:
    machine_id, version_id = saved_rule(client)
    analysis_id = create_analysis(client, machine_id, version_id).json()["id"]
    with SessionLocal() as session:
        job = session.scalar(
            select(AnalysisJobModel).where(AnalysisJobModel.analysis_id == analysis_id)
        )
        assert job is not None
        job.state = "RUNNING"
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


def test_source_repository_exposes_no_write_operation() -> None:
    from recipecontrol.source.fixture import FixtureSourceDataRepository

    source = FixtureSourceDataRepository()
    assert not any(hasattr(source, name) for name in ("add", "update", "delete", "execute"))


def test_live_worker_finalizes_marks_active_repairs_and_stops(client: TestClient) -> None:
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
