from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from recipecontrol.source.base import Machine, Sample, Tag

MACHINE = Machine("fixture-line-1", "Fixture Line 1")
TAGS = (
    Tag("temperature", MACHINE.key, "Temperature", "numeric", "°F"),
    Tag("pressure", MACHINE.key, "Pressure", "numeric", "psi"),
    Tag("speed", MACHINE.key, "Speed", "numeric", "ft/min"),
    Tag("alarm_code", MACHINE.key, "Alarm Code", "numeric", None),
    Tag("motor_running", MACHINE.key, "Motor Running", "boolean", None),
)


class FixtureSourceDataRepository:
    """Deterministic source with generated rows for any requested UTC range."""

    def health(self) -> dict[str, object]:
        return {"ok": True, "adapter": "fixture", "mysql_version": None}

    def list_machines(self) -> Sequence[Machine]:
        return (MACHINE,)

    def search_tags(self, machine_key: str, query: str = "") -> Sequence[Tag]:
        if machine_key != MACHINE.key:
            return ()
        needle = query.casefold()
        return tuple(tag for tag in TAGS if needle in tag.display_name.casefold())

    def get_samples(
        self, tag_keys: Sequence[str], start_utc: datetime, end_utc: datetime
    ) -> Iterable[Sample]:
        start = start_utc.astimezone(UTC).replace(second=0, microsecond=0)
        end = end_utc.astimezone(UTC)
        minute = start
        row_id = 1
        while minute < end:
            cycle = int(minute.timestamp() // 60) % 60
            for tag_key in tag_keys:
                # Intentional absent pressure row and NULL speed row once per cycle.
                if tag_key == "pressure" and cycle == 31:
                    continue
                value: object | None
                if tag_key == "temperature":
                    value = Decimal("260") if 5 <= cycle <= 24 else Decimal("245")
                elif tag_key == "pressure":
                    value = Decimal("35") if 9 <= cycle <= 27 else Decimal("50")
                elif tag_key == "speed":
                    value = None if cycle == 32 else Decimal(cycle * 5)
                elif tag_key == "alarm_code":
                    value = Decimal("12") if 40 <= cycle <= 45 else Decimal("0")
                elif tag_key == "motor_running":
                    value = not (40 <= cycle <= 47)
                else:
                    continue
                yield Sample(tag_key, minute + timedelta(seconds=10), value, row_id)
                row_id += 1
                # Duplicate and exact-timestamp tie cases; greatest key must win.
                if tag_key == "temperature" and cycle == 5:
                    yield Sample(tag_key, minute + timedelta(seconds=50), Decimal("260"), row_id)
                    row_id += 1
                if tag_key == "alarm_code" and cycle == 40:
                    stamp = minute + timedelta(seconds=20)
                    yield Sample(tag_key, stamp, Decimal("0"), row_id)
                    row_id += 1
                    yield Sample(tag_key, stamp, Decimal("12"), row_id)
                    row_id += 1
            minute += timedelta(minutes=1)
