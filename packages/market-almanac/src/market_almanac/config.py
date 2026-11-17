"""Runtime configuration.

All configuration comes from environment variables (optionally loaded from a local
``.env`` file that is never committed). Secrets are held as ``SecretStr`` so they are
never rendered in reprs, logs, or API responses.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RunMode(StrEnum):
    DEMO = "demo"
    LIVE = "live"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False)

    app_env: str = "development"
    log_level: str = "INFO"
    market_almanac_mode: RunMode = Field(default=RunMode.DEMO, alias="MARKET_ALMANAC_MODE")

    # Storage. DATABASE_URL may point at PostgreSQL (recommended) or SQLite (zero-setup demo).
    database_url: str = "sqlite:///./data/market-almanac.db"
    data_dir: Path = Path("./data")
    cache_dir: Path = Path("./data/cache")

    cors_origins: str = "http://localhost:3000"

    # Provider credentials. Never logged; never sent to the browser.
    hdx_hapi_app_identifier: SecretStr | None = None
    faostat_access_token: SecretStr | None = None
    faostat_username: str | None = None
    faostat_password: SecretStr | None = None

    # HTTP behaviour shared by all providers.
    http_timeout_seconds: float = 60.0
    http_max_retries: int = 4
    http_backoff_base_seconds: float = 1.0
    http_max_concurrency: int = 4
    http_cache_ttl_hours: float = 24.0

    # API protection.
    api_rate_limit_per_minute: int = 120
    api_max_page_size: int = 1000

    @field_validator("database_url")
    @classmethod
    def _normalise_db_url(cls, v: str) -> str:
        # Neon/Heroku style URLs use the plain scheme; SQLAlchemy needs a driver for psycopg3.
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://") :]
        if v.startswith("postgresql://"):
            v = "postgresql+psycopg://" + v[len("postgresql://") :]
        return v

    @property
    def lake_dir(self) -> Path:
        """Parquet dataset root, separated by mode so demo and live data never mix."""
        return self.data_dir / "lake" / self.market_almanac_mode.value

    @property
    def experiments_dir(self) -> Path:
        return self.data_dir / "experiments" / self.market_almanac_mode.value

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def redacted_database_url(self) -> str:
        url = self.database_url
        if "@" in url and "://" in url:
            scheme, rest = url.split("://", 1)
            return f"{scheme}://***@{rest.split('@', 1)[1].split('?', 1)[0]}"
        return url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
