import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import psycopg
import pytest

from mcp_crm.settings import get_settings

if sys.platform == "win32":
    # psycopg's async mode can't use Windows' default Proactor event loop.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests (marked @pytest.mark.anyio) on asyncio."""
    return "asyncio"


@pytest.fixture(scope="session")
def manifest() -> dict[str, Any]:
    """The seed's canary manifest: users, canaries, scenario record IDs."""
    return json.loads((REPO_ROOT / "evals" / "canaries.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def db() -> psycopg.Connection:
    """A plain connection for ground truth. Skips the test if the seeded DB isn't reachable."""
    try:
        s = get_settings()
        conn = psycopg.connect(
            host=s.db_host,
            port=s.db_port,
            dbname=s.db_name,
            user=s.db_user,
            password=s.db_password.get_secret_value(),
            connect_timeout=3,
            autocommit=True,
        )
    except Exception as exc:  # noqa: BLE001 - any failure means "no DB here"
        pytest.skip(f"needs the seeded Postgres (run with --env-file ../../.env): {exc}")
    return conn
