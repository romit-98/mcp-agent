"""Agent settings from AGENT_* environment variables (the SDK reads ANTHROPIC_API_KEY)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

Target = Literal["baseline", "servers"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_", extra="ignore", populate_by_name=True)

    model: str = "claude-haiku-5-5"
    max_tokens: int = 4096
    max_steps: int = 12  # tool-call rounds before the run is stopped (step limit)

    # Which tools the agent talks to. The agent code is identical for every target:
    #   baseline: the insecure all-access server (phase 4, the "before")
    #   servers:  the four secured servers directly, one exchanged token each (phase 5)
    #   (phase 6 adds "gateway")
    target: Target = "baseline"
    baseline_url: str = "http://127.0.0.1:8010/mcp"
    crm_url: str = "http://127.0.0.1:8001/mcp"
    finance_url: str = "http://127.0.0.1:8002/mcp"
    email_url: str = "http://127.0.0.1:8003/mcp"
    knowledge_url: str = "http://127.0.0.1:8004/mcp"

    # Keycloak. The secrets are the same generated values Keycloak imports, read directly
    # from KC_* so they live in .env once.
    keycloak_url: str = "http://localhost:8180"
    keycloak_realm: str = "northstar"
    keycloak_client_id: str = "northstar-agent"
    keycloak_client_secret: SecretStr = Field(
        SecretStr(""), validation_alias="KC_AGENT_CLIENT_SECRET"
    )
    dev_user_password: SecretStr = Field(SecretStr(""), validation_alias="KC_DEV_USER_PASSWORD")


@lru_cache
def get_settings() -> Settings:
    return Settings()
