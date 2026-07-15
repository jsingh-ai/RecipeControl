"""Full historical workflow against the writable application MySQL schema."""

import asyncio
import os
import subprocess
from pathlib import Path

import httpx
import pytest

MYSQL_URL = os.getenv("TEST_APP_MYSQL_URL")
pytestmark = pytest.mark.skipif(not MYSQL_URL, reason="TEST_APP_MYSQL_URL is not configured")
ROOT = Path(__file__).parents[2]


def _alembic(command: str, environment: dict[str, str]) -> None:
    subprocess.run(
        [str(ROOT / ".venv/bin/alembic"), command, "head" if command == "upgrade" else "base"],
        cwd=ROOT,
        env=environment,
        check=True,
    )


def test_full_historical_api_worker_workflow_on_application_mysql() -> None:
    assert MYSQL_URL
    environment = {
        **os.environ,
        "APP_DATABASE_URL": MYSQL_URL,
        "SOURCE_ADAPTER": "fixture",
        "ENABLE_LIVE_MODE": "false",
    }
    os.environ.update(
        {
            "APP_DATABASE_URL": MYSQL_URL,
            "SOURCE_ADAPTER": "fixture",
            "ENABLE_LIVE_MODE": "false",
        }
    )
    _alembic("downgrade", environment)
    _alembic("upgrade", environment)

    from recipecontrol.api import app
    from recipecontrol.worker import run_once

    async def request(method: str, path: str, **kwargs: object) -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://mysql-test") as client:
            return await client.request(method, path, **kwargs)

    def call(method: str, path: str, **kwargs: object) -> httpx.Response:
        return asyncio.run(request(method, path, **kwargs))

    try:
        machine = call("GET", "/api/machines").json()[0]
        created = call(
            "POST",
            "/api/rule-sets",
            json={"machine_id": machine["id"], "name": "MySQL repeated temperature"},
        ).json()
        version_id = created["version"]["id"]
        rule = {
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
        }
        saved = call("PUT", f"/api/rule-versions/{version_id}", json=rule)
        assert saved.status_code == 200
        condition_ids = [item["id"] for item in saved.json()["groups"][0]["conditions"]]
        assert len(condition_ids) == len(set(condition_ids)) == 2
        assert call("POST", f"/api/rule-versions/{version_id}/lock").status_code == 200
        analysis = call(
            "POST",
            "/api/analyses",
            json={
                "machine_id": machine["id"],
                "rule_version_id": version_id,
                "selected_start_utc": "2026-06-11T19:50:00Z",
                "selected_end_utc": "2026-06-23T14:20:00Z",
            },
        ).json()
        assert run_once("mysql-full-workflow")
        analysis_id = analysis["id"]
        assert call("GET", f"/api/analyses/{analysis_id}").json()["status"] == "COMPLETE"
        timeline = call("GET", f"/api/analyses/{analysis_id}/timeline").json()
        segments = timeline["segments"]
        assert segments[0]["start_utc"].startswith("2026-06-11T19:50")
        # The API end minute is inclusive; persisted coverage is half-open.
        assert segments[-1]["end_utc"].startswith("2026-06-23T14:21")
        assert all(
            left["end_utc"] == right["start_utc"]
            for left, right in zip(segments, segments[1:], strict=False)
        )
        exact = call("GET", f"/api/analyses/{analysis_id}/minutes/2026-06-11T20:10:00+00:00")
        assert exact.status_code == 200
        segment = segments[0]
        annotated = call(
            "PATCH",
            f"/api/analyses/{analysis_id}/segments/{segment['id']}",
            json={"quality_label": "UNSURE", "note": "MySQL persisted review"},
        )
        assert annotated.status_code == 200
        assert call("GET", f"/api/segments/{segment['id']}").json()["note"] == (
            "MySQL persisted review"
        )
        rule_set_id = created["rule_set_id"]
        assert call("POST", f"/api/rule-sets/{rule_set_id}/archive").status_code == 200
        assert call("GET", f"/api/analyses/{analysis_id}/timeline").status_code == 200
        assert call("GET", f"/api/rule-versions/{version_id}").status_code == 200
    finally:
        _alembic("downgrade", environment)
