"""Northstar CRM MCP server."""

import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.mcpserver import Context, MCPServer
from psycopg_pool import AsyncConnectionPool

from mcp_crm.settings import get_settings


@dataclass(frozen=True)
class AppState:
    """Shared for the server's lifetime; tools reach it through the request context."""

    pool: AsyncConnectionPool


@asynccontextmanager
async def lifespan(_: MCPServer) -> AsyncIterator[AppState]:
    """Open one connection pool at startup and close it at shutdown."""
    s = get_settings()
    pool = AsyncConnectionPool(
        kwargs={
            "host": s.db_host,
            "port": s.db_port,
            "dbname": s.db_name,
            "user": s.db_user,
            "password": s.db_password.get_secret_value(),
            "connect_timeout": 5,
            "application_name": "mcp-crm",  # shows in pg_stat_activity
        },
        min_size=1,
        max_size=5,
        open=False,
        name="mcp-crm",
    )
    # Fail at startup, not on the first request, if the database is unreachable.
    await pool.open(wait=True, timeout=10)
    try:
        yield AppState(pool=pool)
    finally:
        await pool.close()


mcp = MCPServer("northstar-crm", lifespan=lifespan)


def pool_from(ctx: Context) -> AsyncConnectionPool:
    state: AppState = ctx.request_context.lifespan_context
    return state.pool


@mcp.tool()
async def ping(ctx: Context) -> str:
    """Check the Northstar CRM MCP server is alive and can reach its database."""
    async with pool_from(ctx).connection() as conn:
        await conn.execute("SELECT 1")
    return "pong (db ok)"


def main() -> None:
    if sys.platform == "win32":
        # psycopg's async mode can't use Windows' default Proactor event loop.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    s = get_settings()
    mcp.run(transport="streamable-http", host=s.host, port=s.port, stateless_http=True)


if __name__ == "__main__":
    main()
