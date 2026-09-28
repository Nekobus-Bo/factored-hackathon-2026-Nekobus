FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Optional extras, e.g. --build-arg BANKING_CORE_SYNC_ARGS="--extra vector" for
# the dense kb.search backend (CPU-only torch on Linux, see root pyproject).
ARG BANKING_CORE_SYNC_ARGS=""

COPY pyproject.toml uv.lock ./
COPY packages/contracts ./packages/contracts
COPY packages/retrieval ./packages/retrieval
COPY apps/banking-core/pyproject.toml ./apps/banking-core/pyproject.toml

RUN uv sync --frozen --no-install-project --no-dev --package banking-core ${BANKING_CORE_SYNC_ARGS} \
    && uv cache clean

COPY apps/banking-core/alembic.ini ./apps/banking-core/alembic.ini
COPY apps/banking-core/migrations ./apps/banking-core/migrations
COPY apps/banking-core/src ./apps/banking-core/src

RUN uv sync --frozen --no-dev --package banking-core ${BANKING_CORE_SYNC_ARGS} && uv cache clean

RUN useradd -m -u 1000 appuser \
    && mkdir -p /models/hf && chown appuser:appuser /models/hf

# Embedding model cache (the hf-cache volume, filled by `make warmup`).
ENV HF_HOME=/models/hf

USER appuser

EXPOSE 8081

CMD ["uvicorn", "banking_core.main:app", "--host", "0.0.0.0", "--port", "8081"]
