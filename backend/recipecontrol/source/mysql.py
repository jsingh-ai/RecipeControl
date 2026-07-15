from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import bindparam, create_engine, event, text
from sqlalchemy.engine import Engine

from recipecontrol.config import Settings
from recipecontrol.source.base import Machine, Sample, Tag, TagPage

NUMERIC_OPC_TYPES = frozenset(
    {
        "byte",
        "sbyte",
        "int16",
        "uint16",
        "int32",
        "uint32",
        "int64",
        "uint64",
        "float",
        "double",
        "decimal",
        "number",
        "integer",
        "uinteger",
    }
)


def normalize_data_kind(raw_data_type: str | None) -> str:
    normalized = (raw_data_type or "").strip().casefold()
    if normalized in NUMERIC_OPC_TYPES:
        return "numeric"
    if normalized == "boolean":
        return "boolean"
    return "text"


def display_name(display_name: object, browse_name: object, node_id: object) -> str:
    for candidate in (display_name, browse_name, node_id):
        if candidate is not None and str(candidate).strip():
            return str(candidate).strip()
    raise ValueError("Collector tag has no usable display_name, browse_name, or node_id")


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _decode_boolean(numeric: object | None, textual: object | None) -> bool | None:
    if numeric is not None:
        number = Decimal(str(numeric))
        if number in {Decimal(0), Decimal(1)}:
            return bool(number)
    if textual is not None:
        normalized = str(textual).strip().casefold()
        if normalized in {"true", "1"}:
            return True
        if normalized in {"false", "0"}:
            return False
    return None


def decode_typed_value(
    data_kind: str, value_numeric: object | None, value_text: object | None
) -> object | None:
    if data_kind == "numeric":
        return None if value_numeric is None else Decimal(str(value_numeric))
    if data_kind == "boolean":
        return _decode_boolean(value_numeric, value_text)
    return None if value_text is None else str(value_text)


class MySQLSourceDataRepository:
    """Exact-schema, read-only adapter for the opcua_collector database."""

    def __init__(self, settings: Settings, engine: Engine | None = None) -> None:
        source_url = settings.source_database_url
        if not source_url and engine is None:
            raise ValueError("SOURCE_DATABASE_URL is required for the mysql adapter")
        self.engine = engine or create_engine(
            source_url or "", pool_pre_ping=True, pool_recycle=3600
        )
        if engine is None:
            event.listen(self.engine, "connect", self._set_utc_session)

    @staticmethod
    def _set_utc_session(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("SET SESSION time_zone = '+00:00'")
        finally:
            cursor.close()

    def health(self) -> dict[str, object]:
        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT VERSION() AS version, @@session.time_zone AS session_time_zone")
            ).one()
        return {
            "ok": True,
            "adapter": "mysql-opcua-collector",
            "mysql_version": str(row.version),
            "session_time_zone": str(row.session_time_zone),
        }

    def list_machines(self) -> Sequence[Machine]:
        statement = text(
            "SELECT id, machine_name FROM machines WHERE enabled = 1 ORDER BY machine_name"
        )
        with self.engine.connect() as connection:
            return tuple(
                Machine(str(row.id), str(row.machine_name)) for row in connection.execute(statement)
            )

    @staticmethod
    def _tag(row: object) -> Tag:
        raw_type = None if row.data_type is None else str(row.data_type)  # type: ignore[attr-defined]
        return Tag(
            key=str(row.id),  # type: ignore[attr-defined]
            machine_key=str(row.machine_id),  # type: ignore[attr-defined]
            display_name=display_name(row.display_name, row.browse_name, row.node_id),  # type: ignore[attr-defined]
            raw_data_type=raw_type,
            data_kind=normalize_data_kind(raw_type),
            node_id=str(row.node_id),  # type: ignore[attr-defined]
            opc_path=None if row.opc_path is None else str(row.opc_path),  # type: ignore[attr-defined]
        )

    def search_tags(
        self, machine_key: str, query: str = "", *, limit: int = 50, offset: int = 0
    ) -> TagPage:
        limit = min(max(limit, 1), 200)
        offset = max(offset, 0)
        statement = text(
            "SELECT id, machine_id, node_id, opc_path, display_name, browse_name, data_type "
            "FROM tags WHERE machine_id = :machine_id AND enabled = 1 "
            "AND (:query = '' OR LOWER(COALESCE(display_name, '')) LIKE :pattern "
            "OR LOWER(COALESCE(browse_name, '')) LIKE :pattern "
            "OR LOWER(node_id) LIKE :pattern OR LOWER(COALESCE(opc_path, '')) LIKE :pattern) "
            "ORDER BY COALESCE(NULLIF(TRIM(display_name), ''), "
            "NULLIF(TRIM(browse_name), ''), node_id), id LIMIT :fetch_limit OFFSET :offset"
        )
        params = {
            "machine_id": int(machine_key),
            "query": query.strip().casefold(),
            "pattern": f"%{query.strip().casefold()}%",
            "fetch_limit": limit + 1,
            "offset": offset,
        }
        with self.engine.connect() as connection:
            rows = list(connection.execute(statement, params))
        return TagPage(
            tuple(self._tag(row) for row in rows[:limit]), limit, offset, len(rows) > limit
        )

    def resolve_tags(
        self, machine_key: str, tag_keys: Sequence[str], *, include_disabled: bool = False
    ) -> Sequence[Tag]:
        if not tag_keys:
            return ()
        statement = text(
            "SELECT id, machine_id, node_id, opc_path, display_name, browse_name, data_type "
            "FROM tags WHERE machine_id = :machine_id "
            + ("" if include_disabled else "AND enabled = 1 ")
            + "AND id IN :tag_ids ORDER BY id"
        ).bindparams(bindparam("tag_ids", expanding=True))
        with self.engine.connect() as connection:
            rows = connection.execute(
                statement,
                {"machine_id": int(machine_key), "tag_ids": [int(key) for key in tag_keys]},
            )
            return tuple(self._tag(row) for row in rows)

    def sample_bounds(self, machine_key: str) -> tuple[datetime | None, datetime | None]:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT MIN(sampled_at_utc) AS minimum_utc, "
                    "MAX(sampled_at_utc) AS maximum_utc FROM tag_samples "
                    "WHERE machine_id = :machine_id"
                ),
                {"machine_id": int(machine_key)},
            ).one()
        minimum = row.minimum_utc
        maximum = row.maximum_utc
        if minimum is not None and minimum.tzinfo is None:
            minimum = minimum.replace(tzinfo=UTC)
        if maximum is not None and maximum.tzinfo is None:
            maximum = maximum.replace(tzinfo=UTC)
        return minimum, maximum

    def get_samples(
        self,
        machine_key: str,
        tag_kinds: Mapping[str, str],
        start_utc: datetime,
        end_utc: datetime,
    ) -> Iterable[Sample]:
        if not tag_kinds:
            return
        statement = text(
            "SELECT ts.id, ts.tag_id, ts.machine_id, ts.sampled_at_utc, "
            "ts.value_numeric, ts.value_text, ts.quality, ts.status_code, ts.error_text "
            "FROM tag_samples ts WHERE ts.machine_id = :machine_id "
            "AND ts.tag_id IN :tag_ids AND ts.sampled_at_utc >= :start_utc "
            "AND ts.sampled_at_utc < :end_utc "
            "ORDER BY ts.sampled_at_utc, ts.tag_id, ts.id"
        ).bindparams(bindparam("tag_ids", expanding=True))
        params = {
            "machine_id": int(machine_key),
            "tag_ids": [int(key) for key in tag_kinds],
            "start_utc": _utc_naive(start_utc),
            "end_utc": _utc_naive(end_utc),
        }
        with self.engine.connect().execution_options(stream_results=True) as connection:
            for row in connection.execute(statement, params):
                stamp = row.sampled_at_utc
                stamp = stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)
                key = str(row.tag_id)
                yield Sample(
                    key,
                    stamp,
                    decode_typed_value(tag_kinds[key], row.value_numeric, row.value_text),
                    row.id,
                    str(row.quality) if row.quality is not None else None,
                    str(row.status_code) if row.status_code is not None else None,
                    str(row.error_text) if row.error_text is not None else None,
                )
