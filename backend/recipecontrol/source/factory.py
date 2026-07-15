import os
from functools import lru_cache

from recipecontrol.config import get_settings
from recipecontrol.source.base import SourceDataRepository
from recipecontrol.source.fixture import FixtureSourceDataRepository


@lru_cache(maxsize=1)
def _process_repository() -> tuple[int, SourceDataRepository]:
    settings = get_settings()
    if settings.source_adapter.casefold() == "fixture":
        repository: SourceDataRepository = FixtureSourceDataRepository()
    elif settings.source_adapter.casefold() == "mysql":
        from recipecontrol.source.mysql import MySQLSourceDataRepository

        repository = MySQLSourceDataRepository(settings)
    else:
        raise ValueError(f"Unknown SOURCE_ADAPTER: {settings.source_adapter!r}")
    return os.getpid(), repository


def get_source_repository() -> SourceDataRepository:
    process_id, repository = _process_repository()
    if process_id != os.getpid():
        _process_repository.cache_clear()
        process_id, repository = _process_repository()
    return repository


def dispose_source_repository() -> None:
    if _process_repository.cache_info().currsize:
        _, repository = _process_repository()
        repository.dispose()
        _process_repository.cache_clear()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_process_repository.cache_clear)
