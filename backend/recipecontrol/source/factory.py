from recipecontrol.config import get_settings
from recipecontrol.source.base import SourceDataRepository
from recipecontrol.source.fixture import FixtureSourceDataRepository


def get_source_repository() -> SourceDataRepository:
    settings = get_settings()
    if settings.source_adapter.casefold() == "fixture":
        return FixtureSourceDataRepository()
    if settings.source_adapter.casefold() == "mysql":
        from recipecontrol.source.mysql import MySQLSourceDataRepository

        return MySQLSourceDataRepository(settings)
    raise ValueError(f"Unknown SOURCE_ADAPTER: {settings.source_adapter!r}")
