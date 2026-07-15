# ruff: noqa: E501 -- exact authoritative collector DDL is kept verbatim in test setup.
import os
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text

from recipecontrol.config import Settings
from recipecontrol.domain.engine import segment_timeline
from recipecontrol.domain.models import (
    Condition,
    ConditionOperator,
    DataType,
    Group,
    LogicOperator,
    RuleDefinition,
    SystemState,
)
from recipecontrol.source.mysql import MySQLSourceDataRepository

MYSQL_URL = os.getenv("TEST_COLLECTOR_MYSQL_URL")
pytestmark = pytest.mark.skipif(not MYSQL_URL, reason="TEST_COLLECTOR_MYSQL_URL is not configured")


@pytest.fixture()
def source() -> MySQLSourceDataRepository:
    assert MYSQL_URL
    admin = create_engine(MYSQL_URL)
    statements = [
        "DROP TABLE IF EXISTS tag_samples",
        "DROP TABLE IF EXISTS tags",
        "DROP TABLE IF EXISTS machines",
        "CREATE TABLE machines (id BIGINT UNSIGNED PRIMARY KEY, machine_name VARCHAR(100) NOT NULL, enabled TINYINT(1) NOT NULL)",
        "CREATE TABLE tags (id BIGINT UNSIGNED PRIMARY KEY, machine_id BIGINT UNSIGNED NOT NULL, node_id VARCHAR(512) NOT NULL, opc_path TEXT, display_name VARCHAR(255) NULL, browse_name VARCHAR(255) NULL, data_type VARCHAR(120) NULL, parent_branch VARCHAR(120) NULL, enabled TINYINT(1) NOT NULL)",
        "CREATE TABLE tag_samples (id BIGINT UNSIGNED PRIMARY KEY, tag_id BIGINT UNSIGNED NOT NULL, machine_id BIGINT UNSIGNED NOT NULL, sampled_at_utc DATETIME(6) NOT NULL, source_timestamp_utc DATETIME(6) NULL, server_timestamp_utc DATETIME(6) NULL, value_numeric DOUBLE NULL, value_text TEXT NULL, quality VARCHAR(40) NOT NULL, status_code VARCHAR(120) NULL, error_text TEXT NULL, created_at_utc DATETIME(6) NOT NULL)",
        "INSERT INTO machines VALUES (1, 'Line A', 1), (2, 'Disabled Line', 0), (3, 'Line B', 1)",
        "INSERT INTO tags VALUES (10,1,'ns=2;s=temp','Plant/Temp',' Motor Temp ',NULL,'Double',NULL,1),(11,1,'ns=2;s=run','Plant/Run','', 'Running','Boolean',NULL,1),(12,1,'ns=2;s=message','Plant/Alarm',NULL,'','String',NULL,1),(13,1,'ns=2;s=alarm','Plant/Code','Alarm Code',NULL,'Int32',NULL,1),(14,1,'ns=2;s=disabled',NULL,'Disabled',NULL,'Double',NULL,0),(30,3,'ns=2;s=other',NULL,'Other',NULL,'Double',NULL,1)",
        "INSERT INTO tag_samples (id,tag_id,machine_id,sampled_at_utc,value_numeric,value_text,quality,status_code,error_text,created_at_utc) VALUES (1,10,1,'2026-06-23 14:19:05.000000',5,NULL,'Good','Good',NULL,'2026-06-23 14:19:06'),(2,10,1,'2026-06-23 14:19:50.000000',7,NULL,'Uncertain','0x4000','late','2026-06-23 14:19:51'),(3,10,1,'2026-06-23 14:19:50.000000',8,NULL,'Good','Good',NULL,'2026-06-23 14:19:52'),(4,11,1,'2026-06-23 14:20:01.000000',1,NULL,'Good',NULL,NULL,'2026-06-23 14:20:02'),(5,11,1,'2026-06-23 14:20:02.000000',NULL,'false','Good',NULL,NULL,'2026-06-23 14:20:03'),(6,12,1,'2026-06-23 14:20:03.000000',NULL,'','Bad','BadText','alarm','2026-06-23 14:20:04'),(7,13,1,'2026-06-23 14:20:04.000000',12,NULL,'Good',NULL,NULL,'2026-06-23 14:20:05'),(8,10,1,'2026-06-23 14:20:05.000000',NULL,NULL,'Bad','Null',NULL,'2026-06-23 14:20:06'),(9,10,1,'2026-06-23 14:21:00.000000',99,NULL,'Good',NULL,NULL,'2026-06-23 14:21:01'),(10,10,3,'2026-06-23 14:20:05.000000',123,NULL,'Good',NULL,NULL,'2026-06-23 14:20:06')",
    ]
    with admin.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
    admin.dispose()
    settings = Settings(
        app_database_url="sqlite://",
        source_adapter="mysql",
        source_database_url=MYSQL_URL,
    )
    return MySQLSourceDataRepository(settings)


def test_exact_collector_metadata_queries(source: MySQLSourceDataRepository) -> None:
    assert [(item.key, item.name) for item in source.list_machines()] == [
        ("1", "Line A"),
        ("3", "Line B"),
    ]
    page = source.search_tags("1", "plant", limit=2)
    assert page.has_more and len(page.items) == 2
    all_tags = source.search_tags("1", "", limit=20).items
    assert [item.key for item in all_tags] == ["13", "10", "12", "11"]
    by_id = {item.key: item for item in all_tags}
    assert by_id["10"].display_name == "Motor Temp"
    assert by_id["11"].display_name == "Running"
    assert by_id["12"].display_name == "ns=2;s=message"
    assert {key: by_id[key].data_kind for key in by_id} == {
        "10": "numeric",
        "11": "boolean",
        "12": "text",
        "13": "numeric",
    }
    assert source.resolve_tags("1", ["14"]) == ()
    assert source.resolve_tags("1", ["30"]) == ()


def test_exact_schema_sample_decoding_is_half_open_and_machine_scoped(
    source: MySQLSourceDataRepository,
) -> None:
    rows = list(
        source.get_samples(
            "1",
            {"10": "numeric", "11": "boolean", "12": "text", "13": "numeric"},
            datetime(2026, 6, 11, 19, 50, tzinfo=UTC),
            datetime(2026, 6, 23, 14, 21, tzinfo=UTC),
        )
    )
    assert [row.tie_breaker for row in rows] == list(range(1, 9))
    assert rows[2].value == 8
    assert rows[2].quality == "Good"
    assert rows[2].status_code == "Good"
    assert rows[3].value is True and rows[4].value is False
    assert rows[5].value == "" and rows[5].error_text == "alarm"
    assert rows[6].value == 12
    assert rows[7].value is None
    assert all(row.sampled_at_utc.tzinfo is UTC for row in rows)
    minimum, maximum = source.sample_bounds("1")
    assert minimum == datetime(2026, 6, 23, 14, 19, 5, tzinfo=UTC)
    assert maximum == datetime(2026, 6, 23, 14, 21, tzinfo=UTC)


def test_exact_schema_rows_drive_latest_tie_and_gap_engine_semantics(
    source: MySQLSourceDataRepository,
) -> None:
    rows = list(
        source.get_samples(
            "1",
            {"10": "numeric"},
            datetime(2026, 6, 23, 14, 17, tzinfo=UTC),
            datetime(2026, 6, 23, 14, 21, tzinfo=UTC),
        )
    )
    rule = RuleDefinition(
        LogicOperator.OR,
        (
            Group(
                1,
                LogicOperator.OR,
                (
                    Condition(
                        1,
                        "10",
                        "Motor Temp",
                        DataType.NUMERIC,
                        ConditionOperator.ABOVE_MAXIMUM,
                        maximum=Decimal("7"),
                    ),
                ),
            ),
        ),
    )
    result = segment_timeline(
        rule,
        rows,
        datetime(2026, 6, 23, 14, 18, tzinfo=UTC),
        datetime(2026, 6, 23, 14, 20, tzinfo=UTC),
    )

    assert [minute.system_state for minute in result.minute_evaluations] == [
        SystemState.DATA_GAP,  # no row at 14:18
        SystemState.BREAK,  # equal timestamps select greatest sample id: value 8
        SystemState.DATA_GAP,  # row exists but both typed value columns are NULL
    ]
    selected = result.minute_evaluations[1].snapshot["conditions"]["1"]
    assert selected["value"] == "8.0"
    assert selected["source"] == {
        "quality": "Good",
        "status_code": "Good",
        "error_text": None,
    }
