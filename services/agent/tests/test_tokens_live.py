"""Against the real Keycloak and the running CRM server (security rules 4 and 10).

Proves end to end: a token exchanged for CRM works; a token for another server, the login
token passed straight through, a forged token, and no token are all refused; and Keycloak
won't issue a Finance token to a contractor. Expiry is covered by the unit tests in
libs/northstar-common, which mint tokens with chosen timestamps.
"""

import time
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from agent.keycloak import TokenError, exchange, sign_in
from agent.settings import Settings

pytestmark = pytest.mark.anyio
REP1 = "5e1f0000-0000-4000-8000-000000000001"


async def call_crm(s: Settings, token: str | None) -> tuple[bool, Any]:
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    async with (
        httpx.AsyncClient(headers=headers, timeout=60) as http,
        streamable_http_client(s.crm_url, http_client=http) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool("search_accounts", {})
    if result.isError:
        return False, " ".join(getattr(b, "text", "") for b in result.content)
    return True, result.structuredContent


async def test_the_users_own_crm_token_works(live: Settings) -> None:
    token_c = await exchange(live, await sign_in(live, "rep1"), "mcp-crm")
    ok, result = await call_crm(live, token_c)
    assert ok, result
    assert len(result["accounts"]) == 17  # rep1's accounts only, decided by the token's sub


async def test_identity_comes_from_the_token_not_the_request(live: Settings) -> None:
    """Same server, same call: finance's token sees every account."""
    token_c = await exchange(live, await sign_in(live, "finance1"), "mcp-crm")
    ok, result = await call_crm(live, token_c)
    assert ok, result
    assert len(result["accounts"]) == 50


async def test_a_token_for_another_server_is_refused(live: Settings) -> None:
    finance_token = await exchange(live, await sign_in(live, "rep1"), "mcp-finance")
    ok, message = await call_crm(live, finance_token)
    assert not ok
    assert message.endswith("unauthenticated")


async def test_the_login_token_cannot_be_passed_through(live: Settings) -> None:
    """Token A names every server in its audience; servers demand a token for them alone."""
    token_a = await sign_in(live, "rep1")
    assert "mcp-crm" in jwt.decode(token_a, options={"verify_signature": False})["aud"]
    ok, message = await call_crm(live, token_a)
    assert not ok
    assert message.endswith("unauthenticated")


async def test_a_forged_token_is_refused(live: Settings) -> None:
    """Right claims, right shape, wrong signing key: say, someone claiming to be finance."""
    now = int(time.time())
    forged = jwt.encode(
        {
            "iss": f"{live.keycloak_url}/realms/{live.keycloak_realm}",
            "aud": "mcp-crm",
            "sub": REP1,
            "typ": "Bearer",
            "iat": now,
            "exp": now + 300,
            "realm_access": {"roles": ["finance_analyst"]},
        },
        rsa.generate_private_key(public_exponent=65537, key_size=2048),
        algorithm="RS256",
        headers={"kid": "made-up"},
    )
    ok, message = await call_crm(live, forged)
    assert not ok
    assert message.endswith("unauthenticated")


async def test_no_token_is_refused(live: Settings) -> None:
    ok, message = await call_crm(live, None)
    assert not ok
    assert message.endswith("unauthenticated")


async def test_keycloak_wont_issue_a_finance_token_to_a_contractor(live: Settings) -> None:
    token_a = await sign_in(live, "contractor1")
    with pytest.raises(TokenError, match="audience not available"):
        await exchange(live, token_a, "mcp-finance")
    assert await exchange(live, token_a, "mcp-knowledge")  # but documents are fine


async def test_exchanged_token_keeps_the_user_and_never_outlives_the_login(live: Settings) -> None:
    token_a = await sign_in(live, "rep1")
    token_c = await exchange(live, token_a, "mcp-crm")
    a = jwt.decode(token_a, options={"verify_signature": False})
    c = jwt.decode(token_c, options={"verify_signature": False})
    assert c["sub"] == a["sub"] == REP1
    assert c["aud"] == "mcp-crm"
    assert c["exp"] <= a["exp"]
