"""Identity for the CRM server. The logic lives in northstar_common (shared by every server)."""

from mcp.server.mcpserver import Context

from mcp_crm.settings import get_settings
from northstar_common import identity
from northstar_common.identity import Identity, Role
from northstar_common.tokens import validator_for

__all__ = ["Identity", "Role", "current_user"]


def current_user(ctx: Context) -> Identity:
    """The caller's identity from its token (or dev headers if enabled), else Unauthenticated."""
    s = get_settings()
    return identity.current_user(ctx, dev_auth=s.dev_auth, validator=validator_for(s))
