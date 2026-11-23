"""Which customer accounts a caller may see (spec section 3).

CRM, Finance and Email all scope by account ownership, so the rule lives here once.
App-level check; Postgres row-level security backs it up in phase 6.
"""

from dataclasses import dataclass
from uuid import UUID

from northstar_common.errors import Forbidden
from northstar_common.identity import Identity


@dataclass(frozen=True)
class AccountScope:
    user_id: UUID
    see_all: bool  # False unless explicitly granted, so a bug narrows access, never widens it


def account_scope(identity: Identity) -> AccountScope:
    """Deny by default: only roles listed here see any customer accounts."""
    match identity.role:
        case "finance_analyst":
            return AccountScope(user_id=identity.user_id, see_all=True)
        case "sales_rep":
            return AccountScope(user_id=identity.user_id, see_all=False)
        case _:
            raise Forbidden()


# Every query that touches account data joins crm.accounts AS a and includes this filter,
# with params from AccountScope (asdict(scope)).
VISIBLE_ACCOUNT = "(%(see_all)s OR a.owner_user_id = %(user_id)s)"
