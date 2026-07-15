from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    source_machine_table: str | None = None
    source_machine_id_column: str | None = None
    source_machine_name_column: str | None = None
    source_tag_table: str | None = None
    source_tag_id_column: str | None = None
    source_tag_machine_id_column: str | None = None
    source_tag_name_column: str | None = None
    source_tag_type_column: str | None = None
    source_tag_units_column: str | None = None
    source_sample_table: str | None = None
    source_sample_id_column: str | None = None
    source_sample_tag_id_column: str | None = None
    source_sample_time_column: str = "sampled_at_utc"
    source_sample_value_column: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
