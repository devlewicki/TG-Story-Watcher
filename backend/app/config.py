from functools import lru_cache
from typing import Annotated, Any

from pydantic import BeforeValidator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _empty_to_none(value: Any) -> Any:
    """Treat an empty/whitespace string (e.g. ``KEY=`` in .env) as ``None``."""
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


# Optional string/int that tolerates an empty env value.
OptStr = Annotated[str | None, BeforeValidator(_empty_to_none)]
OptInt = Annotated[int | None, BeforeValidator(_empty_to_none)]


class Settings(BaseSettings):
    app_name: str = "StoryWatcher"
    secret_key: str = "dev-secret-key"
    debug: bool = False

    # PostgreSQL is the primary target (Docker deployment); the engine falls
    # back to SQLite for quick local runs without a running Postgres.
    database_url: str = (
        "postgresql+psycopg2://storywatcher:storywatcher@localhost:5432/storywatcher"
    )
    redis_url: str = "redis://localhost:6379/0"

    telegram_api_id: OptInt = None
    telegram_api_hash: OptStr = None

    sessions_dir: str = "./sessions"

    api_token: OptStr = Field(default=None, validation_alias="STORYWATCHER_API_TOKEN")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()