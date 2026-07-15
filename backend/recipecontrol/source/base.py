from collections.abc import Iterable, Mapping, Sequence
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
    raw_data_type: str | None
    data_kind: str
    units: str | None = None
    node_id: str | None = None
    opc_path: str | None = None

    @property
    def data_type(self) -> str:
        """Backward-compatible alias for the normalized RecipeControl kind."""
        return self.data_kind


@dataclass(frozen=True, slots=True)
class TagPage:
    items: tuple[Tag, ...]
    limit: int
    offset: int
    has_more: bool


@dataclass(frozen=True, slots=True)
class Sample:
    tag_key: str
    sampled_at_utc: datetime
    value: object | None
    tie_breaker: int | str
    quality: str | None = None
    status_code: str | None = None
    error_text: str | None = None


class SourceDataRepository(Protocol):
    def dispose(self) -> None: ...

    def health(self) -> dict[str, object]: ...

    def diagnostics(self) -> dict[str, object]: ...

    def list_machines(self) -> Sequence[Machine]: ...

    def search_tags(
        self, machine_key: str, query: str = "", *, limit: int = 50, offset: int = 0
    ) -> TagPage: ...

    def resolve_tags(
        self, machine_key: str, tag_keys: Sequence[str], *, include_disabled: bool = False
    ) -> Sequence[Tag]: ...

    def sample_bounds(self, machine_key: str) -> tuple[datetime | None, datetime | None]: ...

    def get_samples(
        self,
        machine_key: str,
        tag_kinds: Mapping[str, str],
        start_utc: datetime,
        end_utc: datetime,
    ) -> Iterable[Sample]: ...
