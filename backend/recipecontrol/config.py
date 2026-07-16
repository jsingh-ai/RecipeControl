from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_database_url: str = "sqlite:///./recipecontrol.db"
    source_adapter: str = "fixture"
    source_database_url: str | None = None
    max_analysis_days: int = Field(default=45, ge=1, le=366)
    max_trend_lookback_minutes: int = Field(default=1440, ge=1)
    live_finalization_lag_minutes: int = Field(default=2, ge=0, le=60)
    note_max_length: int = Field(default=4000, ge=1, le=20000)
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    tag_search_default_limit: int = Field(default=50, ge=1, le=200)
    stale_job_timeout_seconds: int = Field(default=300, ge=30)
    historical_job_max_attempts: int = Field(default=3, ge=1, le=20)
    historical_persistence_lease_seconds: int = Field(default=900, ge=60, le=7200)
    enable_live_mode: bool = False
    serve_frontend: bool = False
    frontend_dist_path: str = "frontend/dist"

    @model_validator(mode="after")
    def separate_source_credential(self) -> "Settings":
        if self.source_adapter.casefold() != "mysql" or not self.source_database_url:
            return self
        app = make_url(self.app_database_url)
        source = make_url(self.source_database_url)
        if (
            app.host == source.host
            and (app.port or 3306) == (source.port or 3306)
            and app.username
            and app.username == source.username
        ):
            raise ValueError(
                "APP_DATABASE_URL must not use the collector read-only credential; "
                "configure a separate writable application account"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
