"""One connection pool per server, and transaction helpers for tools."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Any

from mcp.server.mcpserver import Context
from psycopg import AsyncCursor
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from northstar_common.settings import ServiceSettings


@dataclass(frozen=True)
class AppState:
    """Shared for the server's lifetime; tools reach it through the request context."""

    pool: AsyncConnectionPool


def make_lifespan(
    get_settings: Callable[[], ServiceSettings], app_name: str
) -> Callable[[Any], AbstractAsyncContextManager[AppState]]:
    """Lifespan that opens one pool at startup, fails fast if the DB is down, closes it at exit."""

    @asynccontextmanager
    async def lifespan(_server: Any) -> AsyncIterator[AppState]:
        s = get_settings()
        pool = AsyncConnectionPool(
            kwargs={
                "host": s.db_host,
                "port": s.db_port,
                "dbname": s.db_name,
                "user": s.db_user,
                "password": s.db_password.get_secret_value(),
                "connect_timeout": 5,
                "application_name": app_name,  # shows in pg_stat_activity
            },
            min_size=1,
            max_size=5,
            open=False,
            name=app_name,
        )
        await pool.open(wait=True, timeout=10)
        try:
            yield AppState(pool=pool)
        finally:
            await pool.close()

    return lifespan


def pool_from(ctx: Context) -> AsyncConnectionPool:
    state: AppState = ctx.request_context.lifespan_context
    return state.pool


@asynccontextmanager
async def read_only(ctx: Context) -> AsyncIterator[AsyncCursor[DictRow]]:
    """A cursor in a READ ONLY transaction: read tools can't write, even with a bug."""
    async with pool_from(ctx).connection() as conn, conn.transaction():
        await conn.execute("SET TRANSACTION READ ONLY")
        async with conn.cursor(row_factory=dict_row) as cur:
            yield cur


@asynccontextmanager
async def read_write(ctx: Context) -> AsyncIterator[AsyncCursor[DictRow]]:
    """A cursor in one transaction: commits if the block succeeds, rolls back if it raises."""
    async with pool_from(ctx).connection() as conn, conn.transaction():
        async with conn.cursor(row_factory=dict_row) as cur:
            yield cur
