"""Who is calling. The only place identity is read: every tool goes through current_user().

Until phase 5 this trusts two dev headers. Phase 5 replaces identity_from_headers() with
token validation; nothing else changes. Identity never comes from tool arguments, because
the LLM writes those (security rule 10).
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast, get_args
from uuid import UUID

from mcp.server.mcpserver import Context

from mcp_crm.settings import get_settings

log = logging.getLogger(__name__)

Role = Literal["sales_rep", "finance_analyst", "contractor"]
ROLES: frozenset[str] = frozenset(get_args(Role))

DEV_USER_HEADER = "x-dev-user"
DEV_ROLE_HEADER = "x-dev-role"


class Unauthenticated(PermissionError):
    """No trustworthy identity on the request. The message is deliberately generic."""

    def __init__(self) -> None:
        super().__init__("unauthenticated")


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


def current_user(ctx: Context) -> Identity:
    """Identity of the caller for this request. Raises Unauthenticated if there isn't one."""
    return identity_from_headers(ctx.headers, dev_auth=get_settings().dev_auth)
