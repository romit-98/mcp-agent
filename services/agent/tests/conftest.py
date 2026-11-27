import httpx
import pytest

from agent.settings import Settings


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def live() -> Settings:
    """Settings for the live stack. Skips unless Keycloak and the CRM server are both up."""
    s = Settings()
    if not s.keycloak_client_secret.get_secret_value():
        pytest.skip("needs KC_* secrets: run with --env-file ../../.env")
    try:
        httpx.get(f"{s.keycloak_url}/realms/{s.keycloak_realm}", timeout=5).raise_for_status()
        httpx.get(s.crm_url.removesuffix("/mcp") + "/", timeout=5)
    except httpx.HTTPError as exc:
        pytest.skip(f"needs Keycloak and mcp-crm running (docker compose up -d): {exc}")
    return s
