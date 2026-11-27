"""Who is calling. Every tool in every server goes through current_user().

Until phase 5 this trusts two dev headers. Phase 5 replaces identity_from_headers() with
token validation; no tool changes. Identity never comes from tool arguments, because the LLM
writes those (security rule 10, ADR 0002).
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast, get_args
from uuid import UUID

from mcp.server.mcpserver import Context

from northstar_common.errors import Unauthenticated

if TYPE_CHECKING:
    from northstar_common.tokens import TokenValidator

log = logging.getLogger(__name__)

Role = Literal["sales_rep", "finance_analyst", "contractor"]
ROLES: frozenset[str] = frozenset(get_args(Role))

DEV_USER_HEADER = "x-dev-user"
DEV_ROLE_HEADER = "x-dev-role"


@dataclass(frozen=True)
class Identity:
    user_id: UUID  # becomes the token's `sub` in phase 5
    role: Role


def identity_from_headers(headers: Mapping[str, str] | None, *, dev_auth: bool) -> Identity:
    """Dev stand-in for token validation. Fails closed on anything unexpected."""
    if not dev_auth:
        log.warning("auth denied: dev auth disabled")
        raise Unauthenticated()

    lowered = {k.lower(): v for k, v in (headers or {}).items()}
    raw_user = lowered.get(DEV_USER_HEADER, "").strip()
    raw_role = lowered.get(DEV_ROLE_HEADER, "").strip()

    try:
        user_id = UUID(raw_user)
    except ValueError:
        log.warning("auth denied: missing or malformed user header")
        raise Unauthenticated() from None
    if str(user_id) != raw_user.lower():  # only the canonical 8-4-4-4-12 form
        log.warning("auth denied: non-canonical user id")
        raise Unauthenticated()

    if raw_role not in ROLES:
        log.warning("auth denied: missing or unknown role")
        raise Unauthenticated()

    return Identity(user_id=user_id, role=cast(Role, raw_role))


def identity_from_request(
    headers: Mapping[str, str] | None,
    *,
    dev_auth: bool,
    validator: "TokenValidator | None",
) -> Identity:
    """A bearer token if one was sent; otherwise the dev headers, only if dev auth is on.

    A request that sends an Authorization header is judged on that token alone: a bad token
    never falls back to the dev headers.
    """
    lowered = {k.lower(): v for k, v in (headers or {}).items()}
    authorization = lowered.get("authorization")
    if authorization is not None:
        scheme, _, token = authorization.strip().partition(" ")
        if scheme.lower() != "bearer" or not token.strip() or validator is None:
            log.warning("auth denied: unusable Authorization header")
            raise Unauthenticated()
        return validator.validate(token.strip())
    return identity_from_headers(headers, dev_auth=dev_auth)


def current_user(
    ctx: Context, *, dev_auth: bool, validator: "TokenValidator | None" = None
) -> Identity:
    """Identity of the caller for this request. Raises Unauthenticated if there isn't one."""
    return identity_from_request(ctx.headers, dev_auth=dev_auth, validator=validator)
