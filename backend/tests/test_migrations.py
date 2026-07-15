import os
import subprocess
from pathlib import Path

import pytest


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
