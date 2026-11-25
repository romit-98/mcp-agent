"""Insecure baseline settings, read from INSECURE_* environment variables."""

from functools import lru_cache

from pydantic_settings import SettingsConfigDict

from northstar_common.settings import ServiceSettings


class Settings(ServiceSettings):
    model_config = SettingsConfigDict(env_prefix="INSECURE_", extra="ignore")

    port: int = 8010
    model_cache_dir: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
