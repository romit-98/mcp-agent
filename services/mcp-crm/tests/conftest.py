import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Run async tests (marked @pytest.mark.anyio) on asyncio."""
    return "asyncio"
