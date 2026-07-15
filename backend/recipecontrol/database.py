from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from recipecontrol.config import get_settings


class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


settings = get_settings()
engine_options = (
    {"connect_args": {"check_same_thread": False}}
    if settings.app_database_url.startswith("sqlite")
    else {}
)
engine = create_engine(settings.app_database_url, pool_pre_ping=True, **engine_options)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[Session, None]:
    with SessionLocal() as session:
        yield session
