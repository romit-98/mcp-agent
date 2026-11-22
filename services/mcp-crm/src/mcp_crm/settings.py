"""CRM server settings, read from CRM_* environment variables."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CRM_", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8001
    dev_auth: bool = False  # trust the X-Dev-User header; off unless set, so it fails closed

    db_host: str = "localhost"
    db_port: int = 5433
    db_name: str = "northstar"
    db_user: str
    db_password: SecretStr  # no default: fail fast if missing; shows as ********** in logs


@lru_cache
def get_settings() -> Settings:
    """Load settings once. Tests can call get_settings.cache_clear() to reload."""
    return Settings()
