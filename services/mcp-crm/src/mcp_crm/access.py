"""CRM access: the shared account-ownership rule, plus CRM's search escaping."""

from northstar_common.access import VISIBLE_ACCOUNT, AccountScope
from northstar_common.access import account_scope as crm_scope

__all__ = ["VISIBLE_ACCOUNT", "AccountScope", "crm_scope", "like_pattern"]


def like_pattern(text: str | None) -> str | None:
    """Turn search text into an ILIKE pattern that matches it literally (ESCAPE '\\')."""
    if text is None or not text.strip():
        return None
    escaped = text.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
