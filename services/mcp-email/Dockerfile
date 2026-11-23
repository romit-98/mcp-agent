# syntax=docker/dockerfile:1
# Build from the repo root so the shared library is in the build context:
#   docker build -f services/mcp-email/Dockerfile .

# ---- build: resolve dependencies from the lock file into /app/.venv
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app/services/mcp-email

# Shared library and dependencies first, so code changes don't invalidate this layer.
COPY libs/northstar-common /app/libs/northstar-common
COPY services/mcp-email/pyproject.toml services/mcp-email/uv.lock services/mcp-email/.python-version ./
RUN uv sync --frozen --no-dev --no-editable --no-install-project

COPY services/mcp-email/src ./src
RUN uv sync --frozen --no-dev --no-editable

# ---- runtime: just Python and the virtualenv, running as a non-root user
FROM python:3.12-slim
RUN useradd --system --uid 10001 --no-create-home app
WORKDIR /app
COPY --from=build --chown=app:app /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 \
    EMAIL_HOST=0.0.0.0 EMAIL_PORT=8003
USER app
EXPOSE 8003

# MCP needs a POST to /mcp, so the health check just confirms the port accepts connections.
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import socket; socket.create_connection(('127.0.0.1', 8003), 2)"]

CMD ["python", "-m", "mcp_email.server"]
