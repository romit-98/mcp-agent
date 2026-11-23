"""Email server settings, read from EMAIL_* environment variables."""

from functools import lru_cache

from pydantic_settings import SettingsConfigDict

from northstar_common.settings import ServiceSettings


class Settings(ServiceSettings):
    model_config = SettingsConfigDict(env_prefix="EMAIL_", extra="ignore")

    port: int = 8003
    internal_domain: str = "northstar.example"  # staff addresses; anything else is external


@lru_cache
def get_settings() -> Settings:
    """Load settings once. Tests can call get_settings.cache_clear() to reload."""
    return Settings()
