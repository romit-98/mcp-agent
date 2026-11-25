"""Agent settings from AGENT_* environment variables (the SDK reads ANTHROPIC_API_KEY)."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Target = Literal["baseline", "servers"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_", extra="ignore")

    model: str = "claude-haiku-5-5"
    max_tokens: int = 4096
    max_steps: int = 12  # tool-call rounds before the run is stopped (step limit)

    # Which tools the agent talks to. The agent code is identical for every target:
    #   baseline: the insecure all-access server (phase 4, the "before")
    #   servers:  the four secured servers directly, identity in dev headers
    #   (phase 6 adds "gateway")
    target: Target = "baseline"
    baseline_url: str = "http://127.0.0.1:8010/mcp"
    crm_url: str = "http://127.0.0.1:8001/mcp"
    finance_url: str = "http://127.0.0.1:8002/mcp"
    email_url: str = "http://127.0.0.1:8003/mcp"
    knowledge_url: str = "http://127.0.0.1:8004/mcp"


@lru_cache
def get_settings() -> Settings:
    return Settings()
