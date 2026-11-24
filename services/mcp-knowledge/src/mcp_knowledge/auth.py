"""Identity for the Knowledge server. The logic lives in northstar_common (shared)."""

from mcp.server.mcpserver import Context

from mcp_knowledge.settings import get_settings
from northstar_common import identity
from northstar_common.identity import Identity, Role

__all__ = ["Identity", "Role", "current_user"]


def current_user(ctx: Context) -> Identity:
    """Identity of the caller, honouring KNOW_DEV_AUTH. Raises Unauthenticated if none."""
    return identity.current_user(ctx, dev_auth=get_settings().dev_auth)
