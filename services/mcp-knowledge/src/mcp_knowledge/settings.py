"""Knowledge server settings, read from KNOW_* environment variables."""

from functools import lru_cache

from pydantic_settings import SettingsConfigDict

from northstar_common.settings import ServiceSettings


class Settings(ServiceSettings):
    model_config = SettingsConfigDict(env_prefix="KNOW_", extra="ignore")

    port: int = 8004
    oidc_audience: str = "mcp-knowledge"  # only tokens issued exactly for this server
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384  # must match knowledge.chunks.embedding VECTOR(384)
    model_cache_dir: str | None = None  # None = fastembed's default cache; the image bakes it in


@lru_cache
def get_settings() -> Settings:
    """Load settings once. Tests can call get_settings.cache_clear() to reload."""
    return Settings()
