"""Token validation: every way a token can be wrong is refused (security rules 4 and 10).

Tokens are minted here with our own RSA keys, so no Keycloak is needed. The integration tests
in services/mcp-crm repeat the key cases against the real Keycloak.
"""

import base64
import hashlib
import hmac
import json
import time
from typing import Any
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from northstar_common.errors import Unauthenticated
from northstar_common.identity import Identity, identity_from_request
from northstar_common.tokens import TokenValidator

ISSUER = "http://localhost:8180/realms/northstar"
REP1 = "5e1f0000-0000-4000-8000-000000000001"
REALM_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
VALIDATOR = TokenValidator(ISSUER, "mcp-crm", key_for=lambda _token: REALM_KEY.public_key())


def claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    base = {
        "iss": ISSUER,
        "aud": "mcp-crm",
        "sub": REP1,
        "typ": "Bearer",
        "azp": "northstar-agent",
        "iat": now,
        "exp": now + 300,
        "realm_access": {"roles": ["sales_rep", "default-roles-northstar", "offline_access"]},
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def token(key: Any = REALM_KEY, alg: str = "RS256", **overrides: Any) -> str:
    return jwt.encode(claims(**overrides), key, algorithm=alg)


def test_a_good_token_gives_the_identity() -> None:
    assert VALIDATOR.validate(token()) == Identity(UUID(REP1), "sales_rep")


def test_audience_may_also_be_a_one_item_list() -> None:
    assert VALIDATOR.validate(token(aud=["mcp-crm"])).role == "sales_rep"


@pytest.mark.parametrize(
    "case",
    [
        {"aud": "mcp-finance"},  # wrong audience: a token for another server
        {"aud": ["mcp-crm", "mcp-finance", "northstar-gateway"]},  # the login token: passthrough
        {"iss": "http://evil.example/realms/northstar"},  # wrong issuer
        {"exp": int(time.time()) - 120},  # expired (beyond the 30 s leeway)
        {"nbf": int(time.time()) + 600},  # not valid yet
        {"typ": "ID"},  # an ID token, not an access token
        {"sub": "rep1"},  # not a UUID
        {"sub": REP1.upper()},  # not the canonical form
        {"sub": None},  # missing subject
        {"exp": None},  # missing expiry
        {"aud": None},  # missing audience
        {"realm_access": {"roles": ["offline_access"]}},  # no known role
        {"realm_access": {"roles": ["sales_rep", "finance_analyst"]}},  # ambiguous role
        {"realm_access": None},  # no roles at all
    ],
    ids=lambda c: next(iter(c)),
)
def test_bad_claims_are_refused(case: dict[str, Any]) -> None:
    with pytest.raises(Unauthenticated):
        VALIDATOR.validate(token(**case))


def test_expiry_allows_small_clock_skew_only() -> None:
    assert VALIDATOR.validate(token(exp=int(time.time()) - 10))  # within 30 s leeway
    with pytest.raises(Unauthenticated):
        VALIDATOR.validate(token(exp=int(time.time()) - 31))


def test_signed_by_someone_elses_key_is_refused() -> None:
    with pytest.raises(Unauthenticated):
        VALIDATOR.validate(token(key=OTHER_KEY))


def test_tampered_payload_is_refused() -> None:
    header, payload, signature = token().split(".")
    forged = token(realm_access={"roles": ["finance_analyst"]}).split(".")[1]
    with pytest.raises(Unauthenticated):
        VALIDATOR.validate(f"{header}.{forged}.{signature}")


def test_unsigned_alg_none_is_refused() -> None:
    unsigned = jwt.encode(claims(), key=None, algorithm="none")
    with pytest.raises(Unauthenticated):
        VALIDATOR.validate(unsigned)


def test_hs256_with_the_public_key_as_secret_is_refused() -> None:
    """Algorithm confusion: a forger signs with the *public* key as an HMAC secret."""
    public_pem = REALM_KEY.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    # PyJWT refuses to *create* this token, so build it by hand, as an attacker would.
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    signing_input = f"{header}.{b64(json.dumps(claims()).encode())}"
    signature = hmac.new(public_pem, signing_input.encode(), hashlib.sha256).digest()
    with pytest.raises(Unauthenticated):
        VALIDATOR.validate(f"{signing_input}.{b64(signature)}")


@pytest.mark.parametrize("garbage", ["", "not-a-jwt", "a.b.c", "Bearer x"])
def test_garbage_is_refused(garbage: str) -> None:
    with pytest.raises(Unauthenticated):
        VALIDATOR.validate(garbage)


def test_error_message_never_says_why() -> None:
    with pytest.raises(Unauthenticated, match="^unauthenticated$"):
        VALIDATOR.validate(token(aud="mcp-finance"))


# ----------------------------------------------- bearer token vs dev headers


DEV = {"x-dev-user": REP1, "x-dev-role": "finance_analyst"}


def test_bearer_token_is_used_when_present() -> None:
    who = identity_from_request(
        {"Authorization": f"Bearer {token()}"}, dev_auth=False, validator=VALIDATOR
    )
    assert who.role == "sales_rep"


def test_a_bad_token_never_falls_back_to_dev_headers() -> None:
    headers = {"authorization": f"Bearer {token(aud='mcp-finance')}", **DEV}
    with pytest.raises(Unauthenticated):
        identity_from_request(headers, dev_auth=True, validator=VALIDATOR)


@pytest.mark.parametrize("value", ["Basic cmVwMTpwdw==", "Bearer", "Bearer   ", "token abc"])
def test_unusable_authorization_headers_are_refused(value: str) -> None:
    with pytest.raises(Unauthenticated):
        identity_from_request({"authorization": value, **DEV}, dev_auth=True, validator=VALIDATOR)


def test_a_token_with_no_validator_configured_is_refused() -> None:
    with pytest.raises(Unauthenticated):
        identity_from_request({"authorization": f"Bearer {token()}"}, dev_auth=True, validator=None)


def test_dev_headers_still_work_only_when_dev_auth_is_on() -> None:
    assert identity_from_request(DEV, dev_auth=True, validator=VALIDATOR).role == "finance_analyst"
    with pytest.raises(Unauthenticated):
        identity_from_request(DEV, dev_auth=False, validator=VALIDATOR)
