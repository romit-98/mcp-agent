"""Which CRM rows a caller may see (spec section 3). App-level check; RLS backs it in phase 6."""

from dataclasses import dataclass
from uuid import UUID

from mcp.server.mcpserver.exceptions import ToolError

from mcp_crm.auth import Identity


class Forbidden(ToolError):
    """The caller's role has no access to this tool at all."""

    def __init__(self) -> None:
        super().__init__("forbidden")


class AccountNotFound(ToolError):
    """Missing and not-yours look identical, so the reply can't confirm an account exists."""

    def __init__(self, account_id: str) -> None:
        super().__init__(f"account {account_id} not found")


@dataclass(frozen=True)
class AccountScope:
    user_id: UUID
    see_all: bool  # False unless explicitly granted, so a bug narrows access, never widens it


def crm_scope(identity: Identity) -> AccountScope:
    """Deny by default: only roles listed here get any CRM access."""
    match identity.role:
        case "finance_analyst":
            return AccountScope(user_id=identity.user_id, see_all=True)
        case "sales_rep":
            return AccountScope(user_id=identity.user_id, see_all=False)
        case _:
            raise Forbidden()


# Every account query includes this filter, with params from AccountScope.
VISIBLE_ACCOUNT = "(%(see_all)s OR a.owner_user_id = %(user_id)s)"


def like_pattern(text: str | None) -> str | None:
    """Turn search text into an ILIKE pattern that matches it literally (ESCAPE '\\')."""
    if text is None or not text.strip():
        return None
    escaped = text.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
