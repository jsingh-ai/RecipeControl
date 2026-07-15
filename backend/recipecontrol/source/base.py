from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Machine:
    key: str
    name: str


@dataclass(frozen=True, slots=True)
class Tag:
    key: str
    machine_key: str
    display_name: str
    data_type: str
    units: str | None = None


@dataclass(frozen=True, slots=True)
class Sample:
    tag_key: str
    sampled_at_utc: datetime
    value: object | None
    tie_breaker: int | str


class SourceDataRepository(Protocol):
    def health(self) -> dict[str, object]: ...

    def list_machines(self) -> Sequence[Machine]: ...

    def search_tags(self, machine_key: str, query: str = "") -> Sequence[Tag]: ...

    def get_samples(
        self, tag_keys: Sequence[str], start_utc: datetime, end_utc: datetime
    ) -> Iterable[Sample]: ...
