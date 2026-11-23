"""Identity for the Email server. The logic lives in northstar_common (shared by every server)."""

from mcp.server.mcpserver import Context

from mcp_email.settings import get_settings
from northstar_common import identity
from northstar_common.identity import Identity, Role

__all__ = ["Identity", "Role", "current_user"]


def current_user(ctx: Context) -> Identity:
    """Identity of the caller, honouring EMAIL_DEV_AUTH. Raises Unauthenticated if none."""
    return identity.current_user(ctx, dev_auth=get_settings().dev_auth)
