FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY apps/orchestrator/pyproject.toml ./apps/orchestrator/pyproject.toml
COPY packages/contracts ./packages/contracts

RUN uv sync --frozen --no-install-project --no-dev --package orchestrator

COPY apps/orchestrator/src ./apps/orchestrator/src
# The effects file (ADR-0012): behavior as data, read at startup.
COPY apps/orchestrator/config ./apps/orchestrator/config

RUN uv sync --frozen --no-dev --package orchestrator && uv cache clean

RUN useradd -m -u 1000 appuser

USER appuser

EXPOSE 8080

CMD ["uvicorn", "orchestrator.main:app", "--host", "0.0.0.0", "--port", "8080"]
