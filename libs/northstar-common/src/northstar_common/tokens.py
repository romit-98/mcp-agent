"""Validate access tokens from Keycloak (security rules 4 and 10).

A token is accepted only if every check passes; anything else is `Unauthenticated`:
  - signature: RS256 only, with a key from the realm's published JWKS (no "none", no HS256)
  - issuer: exactly the configured realm URL
  - audience: exactly this server, and nothing else. The login token lists every server, so
    passing it straight through is refused; each server needs its own exchanged token.
  - expiry and not-before, with a small clock-skew allowance
  - type: an access token ("Bearer"), not an ID token
  - subject: a canonical UUID (our fixed user IDs)
  - role: exactly one of our known roles
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, cast
from uuid import UUID

import jwt

from northstar_common.errors import Unauthenticated
from northstar_common.identity import ROLES, Identity, Role

log = logging.getLogger(__name__)

ALGORITHMS = ["RS256"]
REQUIRED_CLAIMS = ["exp", "iat", "iss", "aud", "sub"]

KeyResolver = Callable[[str], Any]  # token -> public key that should have signed it


@dataclass(frozen=True)
class TokenValidator:
    issuer: str
    audience: str
    key_for: KeyResolver
    leeway_seconds: int = 30

    def validate(self, token: str) -> Identity:
        try:
            return self._validate(token)
        except Unauthenticated:
            raise
        except Exception as exc:  # noqa: BLE001 - every failure is the same answer to the caller
            log.warning("token rejected: %s", type(exc).__name__)
            raise Unauthenticated() from None

    def _validate(self, token: str) -> Identity:
        header = jwt.get_unverified_header(token)
        if header.get("alg") not in ALGORITHMS:
            return self._deny("algorithm not allowed")

        claims = jwt.decode(
            token,
            self.key_for(token),
            algorithms=ALGORITHMS,
            audience=self.audience,
            issuer=self.issuer,
            leeway=self.leeway_seconds,
            options={"require": REQUIRED_CLAIMS},
        )

        aud = claims["aud"]
        if (aud if isinstance(aud, list) else [aud]) != [self.audience]:
            return self._deny("token is not for this server only")
        if claims.get("typ") != "Bearer":
            return self._deny("not an access token")

        sub = str(claims["sub"])
        try:
            user_id = UUID(sub)
        except ValueError:
            return self._deny("subject is not a UUID")
        if str(user_id) != sub:  # exactly the canonical lowercase form Keycloak issues
            return self._deny("subject is not canonical")

        roles = set(claims.get("realm_access", {}).get("roles", [])) & ROLES
        if len(roles) != 1:
            return self._deny("needs exactly one known role")
        return Identity(user_id=user_id, role=cast(Role, roles.pop()))

    @staticmethod
    def _deny(reason: str) -> Identity:
        log.warning("token rejected: %s", reason)
        raise Unauthenticated()


def validator_for(settings: Any) -> TokenValidator | None:
    """The validator for a server's settings, or None if it has no audience configured."""
    if not settings.oidc_audience:
        return None
    return jwks_validator(settings.oidc_issuer, settings.oidc_audience, settings.oidc_jwks_url)


@lru_cache
def jwks_validator(issuer: str, audience: str, jwks_url: str | None = None) -> TokenValidator:
    """Validator backed by the realm's JWKS endpoint (keys cached, refetched on rotation)."""
    url = jwks_url or f"{issuer}/protocol/openid-connect/certs"
    client = jwt.PyJWKClient(url, cache_keys=True, lifespan=300, timeout=5)
    return TokenValidator(
        issuer=issuer,
        audience=audience,
        key_for=lambda token: client.get_signing_key_from_jwt(token).key,
    )
