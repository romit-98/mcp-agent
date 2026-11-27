"""Finance server settings, read from FIN_* environment variables."""

from functools import lru_cache

from pydantic_settings import SettingsConfigDict

from northstar_common.settings import ServiceSettings


class Settings(ServiceSettings):
    model_config = SettingsConfigDict(env_prefix="FIN_", extra="ignore")

    port: int = 8002
    oidc_audience: str = "mcp-finance"  # only tokens issued exactly for this server


@lru_cache
def get_settings() -> Settings:
    """Load settings once. Tests can call get_settings.cache_clear() to reload."""
    return Settings()
