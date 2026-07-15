import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text


def _upgrade_downgrade(root: Path, environment: dict[str, str]) -> None:
    subprocess.run(
        [str(root / ".venv/bin/alembic"), "upgrade", "head"],
        cwd=root,
        env=environment,
        check=True,
    )
    subprocess.run(
        [str(root / ".venv/bin/alembic"), "downgrade", "base"],
        cwd=root,
        env=environment,
        check=True,
    )


def test_explicit_sqlite_upgrade_and_downgrade(tmp_path: Path) -> None:
    database = tmp_path / "migration.db"
    environment = {
        **os.environ,
        "APP_DATABASE_URL": f"sqlite:///{database}",
        "SOURCE_ADAPTER": "fixture",
    }
    root = Path(__file__).parents[2]
    _upgrade_downgrade(root, environment)


def test_explicit_mysql_upgrade_and_downgrade() -> None:
    url = os.getenv("TEST_APP_MYSQL_URL")
    if not url:
        pytest.skip("TEST_APP_MYSQL_URL is not configured")
    root = Path(__file__).parents[2]
    environment = {**os.environ, "APP_DATABASE_URL": url, "SOURCE_ADAPTER": "fixture"}
    _upgrade_downgrade(root, environment)


def test_mysql_schema_has_expected_indexes_foreign_keys_json_and_datetime_precision() -> None:
    url = os.getenv("TEST_APP_MYSQL_URL")
    if not url:
        pytest.skip("TEST_APP_MYSQL_URL is not configured")
    root = Path(__file__).parents[2]
    environment = {**os.environ, "APP_DATABASE_URL": url, "SOURCE_ADAPTER": "fixture"}
    subprocess.run(
        [str(root / ".venv/bin/alembic"), "upgrade", "head"],
        cwd=root,
        env=environment,
        check=True,
    )
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        assert {"rc_analysis", "rc_segment", "rc_analysis_minute"} <= set(
            inspector.get_table_names()
        )
        assert "ix_analysis_duplicate_lookup" in {
            item["name"] for item in inspector.get_indexes("rc_analysis")
        }
        assert "ix_analysis_minute_lookup" in {
            item["name"] for item in inspector.get_indexes("rc_analysis_minute")
        }
        assert any(
            item["referred_table"] == "rc_analysis"
            for item in inspector.get_foreign_keys("rc_segment")
        )
        snapshot = next(
            item
            for item in inspector.get_columns("rc_analysis_minute")
            if item["name"] == "snapshot"
        )
        assert str(snapshot["type"]).upper() == "JSON"
        assert inspector.get_check_constraints("rc_analysis")
        with engine.connect() as connection:
            insufficient = connection.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.columns "
                    "WHERE table_schema = DATABASE() AND table_name LIKE 'rc\\_%' "
                    "AND data_type = 'datetime' AND datetime_precision <> 6"
                )
            ).scalar_one()
        assert insufficient == 0
    finally:
        engine.dispose()
        subprocess.run(
            [str(root / ".venv/bin/alembic"), "downgrade", "base"],
            cwd=root,
            env=environment,
            check=True,
        )
