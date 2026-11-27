"""Sign in as a user, then exchange the login token for one token per MCP server.

  token A: from the user's sign-in; audience lists every server the user's roles allow
  token C: per server, from standard token exchange (RFC 8693); audience is that server only
Each server accepts only a token whose audience is exactly itself, so token A can't be passed
through. Keycloak refuses an exchange the user's roles don't allow (a contractor asking for
Finance), and the agent then simply doesn't get that server's tools.

Phase 6 moves the per-server exchange into the gateway (token A -> gateway token B -> C).
"""

import logging

import httpx

from agent.settings import Settings

log = logging.getLogger(__name__)

TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"  # noqa: S105 - a URN
ACCESS_TOKEN = "urn:ietf:params:oauth:token-type:access_token"  # noqa: S105 - a URN


class TokenError(RuntimeError):
    """Keycloak refused to issue a token."""


def _token_url(s: Settings) -> str:
    return f"{s.keycloak_url}/realms/{s.keycloak_realm}/protocol/openid-connect/token"


async def _post(s: Settings, data: dict[str, str]) -> str:
    auth = (s.keycloak_client_id, s.keycloak_client_secret.get_secret_value())
    async with httpx.AsyncClient(timeout=60) as http:
        response = await http.post(_token_url(s), auth=auth, data=data)
    if response.status_code != 200:
        body = (
            response.json()
            if response.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        reason = body.get("error_description") or body.get("error") or response.status_code
        raise TokenError(reason)
    return response.json()["access_token"]


async def sign_in(s: Settings, username: str) -> str:
    """Token A. Dev users share one generated password (KC_DEV_USER_PASSWORD in .env)."""
    return await _post(
        s,
        {
            "grant_type": "password",
            "username": username,
            "password": s.dev_user_password.get_secret_value(),
            "scope": "openid",
        },
    )


async def exchange(s: Settings, subject_token: str, audience: str) -> str:
    """Token C: a token for exactly one server, for the same user."""
    return await _post(
        s,
        {
            "grant_type": TOKEN_EXCHANGE,
            "subject_token": subject_token,
            "subject_token_type": ACCESS_TOKEN,
            "requested_token_type": ACCESS_TOKEN,
            "audience": audience,
        },
    )


async def tokens_for(s: Settings, username: str, audiences: list[str]) -> dict[str, str]:
    """One token per server the user may use. Servers Keycloak refuses are left out."""
    token_a = await sign_in(s, username)
    tokens: dict[str, str] = {}
    for audience in audiences:
        try:
            tokens[audience] = await exchange(s, token_a, audience)
        except TokenError as exc:
            log.info("no token for %s as %s: %s", audience, username, exc)
    return tokens
