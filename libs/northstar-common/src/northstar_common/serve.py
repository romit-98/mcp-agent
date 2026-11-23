"""Run a server over stateless Streamable HTTP."""

import asyncio
import sys

from mcp.server.mcpserver import MCPServer

from northstar_common.settings import ServiceSettings


def use_selector_loop_on_windows() -> None:
    """psycopg's async mode can't use Windows' default Proactor event loop."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def serve(mcp: MCPServer, settings: ServiceSettings) -> None:
    use_selector_loop_on_windows()
    mcp.run(
        transport="streamable-http", host=settings.host, port=settings.port, stateless_http=True
    )
