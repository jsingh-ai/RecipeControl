import re
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from recipecontrol.config import Settings
from recipecontrol.source.base import Machine, Sample, Tag

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _identifier(value: str | None, setting: str) -> str:
    if value is None or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{setting} must be configured as a safe SQL identifier")
    return value


class MySQLSourceDataRepository:
    """Read-only adapter whose unresolved identifiers are explicit configuration.

    SQLAlchemy is intentionally not given RecipeControl ORM models on this engine.
    Only SELECT statements exist in this module.
    """

    def __init__(self, settings: Settings, engine: Engine | None = None) -> None:
        if not settings.source_database_url:
            raise ValueError("SOURCE_DATABASE_URL is required for the mysql adapter")
        self.engine = engine or create_engine(settings.source_database_url, pool_pre_ping=True)
        self.machine_table = _identifier(settings.source_machine_table, "SOURCE_MACHINE_TABLE")
        self.machine_id = _identifier(settings.source_machine_id_column, "SOURCE_MACHINE_ID_COLUMN")
        self.machine_name = _identifier(
            settings.source_machine_name_column, "SOURCE_MACHINE_NAME_COLUMN"
        )
        self.tag_table = _identifier(settings.source_tag_table, "SOURCE_TAG_TABLE")
        self.tag_id = _identifier(settings.source_tag_id_column, "SOURCE_TAG_ID_COLUMN")
        self.tag_machine_id = _identifier(
            settings.source_tag_machine_id_column, "SOURCE_TAG_MACHINE_ID_COLUMN"
        )
        self.tag_name = _identifier(settings.source_tag_name_column, "SOURCE_TAG_NAME_COLUMN")
        self.tag_type = _identifier(settings.source_tag_type_column, "SOURCE_TAG_TYPE_COLUMN")
        self.tag_units = (
            _identifier(settings.source_tag_units_column, "SOURCE_TAG_UNITS_COLUMN")
            if settings.source_tag_units_column
            else None
        )
        self.sample_table = _identifier(settings.source_sample_table, "SOURCE_SAMPLE_TABLE")
        self.sample_id = _identifier(settings.source_sample_id_column, "SOURCE_SAMPLE_ID_COLUMN")
        self.sample_tag_id = _identifier(
            settings.source_sample_tag_id_column, "SOURCE_SAMPLE_TAG_ID_COLUMN"
        )
        self.sample_time = _identifier(
            settings.source_sample_time_column, "SOURCE_SAMPLE_TIME_COLUMN"
        )
        self.sample_value = _identifier(
            settings.source_sample_value_column, "SOURCE_SAMPLE_VALUE_COLUMN"
        )

    def health(self) -> dict[str, object]:
        with self.engine.connect() as connection:
            version = connection.execute(text("SELECT VERSION()")).scalar_one()
        return {"ok": True, "adapter": "mysql", "mysql_version": str(version)}

    def list_machines(self) -> Sequence[Machine]:
        statement = text(
            f"SELECT {self.machine_id} AS source_key, {self.machine_name} AS display_name "
            f"FROM {self.machine_table} ORDER BY {self.machine_name}"
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement)
            return tuple(Machine(str(row.source_key), str(row.display_name)) for row in rows)

    def search_tags(self, machine_key: str, query: str = "") -> Sequence[Tag]:
        units = f", {self.tag_units} AS units" if self.tag_units else ", NULL AS units"
        statement = text(
            f"SELECT {self.tag_id} AS source_key, {self.tag_machine_id} AS machine_key, "
            f"{self.tag_name} AS display_name, {self.tag_type} AS data_type {units} "
            f"FROM {self.tag_table} WHERE {self.tag_machine_id} = :machine_key "
            f"AND LOWER({self.tag_name}) LIKE :query ORDER BY {self.tag_name} LIMIT 200"
        )
        with self.engine.connect() as connection:
            rows = connection.execute(
                statement, {"machine_key": machine_key, "query": f"%{query.casefold()}%"}
            )
            return tuple(
                Tag(
                    str(row.source_key),
                    str(row.machine_key),
                    str(row.display_name),
                    str(row.data_type),
                    None if row.units is None else str(row.units),
                )
                for row in rows
            )

    def get_samples(
        self, tag_keys: Sequence[str], start_utc: datetime, end_utc: datetime
    ) -> Iterable[Sample]:
        if not tag_keys:
            return
        placeholders = ", ".join(f":tag_{index}" for index in range(len(tag_keys)))
        statement = text(
            f"SELECT {self.sample_tag_id} AS tag_key, {self.sample_time} AS sampled_at_utc, "
            f"{self.sample_value} AS value, {self.sample_id} AS tie_breaker "
            f"FROM {self.sample_table} WHERE {self.sample_tag_id} IN ({placeholders}) "
            f"AND {self.sample_time} >= :start_utc AND {self.sample_time} < :end_utc "
            f"ORDER BY {self.sample_time}, {self.sample_id}"
        )
        params: dict[str, object] = {f"tag_{index}": key for index, key in enumerate(tag_keys)}
        params.update(
            {
                "start_utc": start_utc.astimezone(UTC).replace(tzinfo=None),
                "end_utc": end_utc.astimezone(UTC).replace(tzinfo=None),
            }
        )
        with self.engine.connect().execution_options(stream_results=True) as connection:
            for row in connection.execute(statement, params):
                stamp = row.sampled_at_utc
                stamp = stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)
                yield Sample(str(row.tag_key), stamp, row.value, row.tie_breaker)
