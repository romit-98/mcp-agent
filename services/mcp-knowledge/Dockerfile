# syntax=docker/dockerfile:1
# Build from the repo root so the shared library is in the build context:
#   docker build -f services/mcp-knowledge/Dockerfile .

# ---- build: dependencies from the lock file into /app/.venv, plus the embedding model
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app/services/mcp-knowledge

COPY libs/northstar-common /app/libs/northstar-common
COPY services/mcp-knowledge/pyproject.toml services/mcp-knowledge/uv.lock services/mcp-knowledge/.python-version ./
RUN uv sync --frozen --no-dev --no-editable --no-install-project

# Bake the model into the image (~67 MB) so the container never downloads at runtime.
RUN /app/.venv/bin/python -c "from fastembed import TextEmbedding; \
TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/app/models')"

COPY services/mcp-knowledge/src ./src
RUN uv sync --frozen --no-dev --no-editable

# ---- runtime: Python, the virtualenv and the model, running as a non-root user
FROM python:3.12-slim
RUN useradd --system --uid 10001 --no-create-home app
WORKDIR /app
COPY --from=build --chown=app:app /app/.venv /app/.venv
COPY --from=build --chown=app:app /app/models /app/models
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 \
    KNOW_HOST=0.0.0.0 KNOW_PORT=8004 KNOW_MODEL_CACHE_DIR=/app/models \
    HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1
USER app
EXPOSE 8004

HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import socket; socket.create_connection(('127.0.0.1', 8004), 2)"]

CMD ["python", "-m", "mcp_knowledge.server"]
