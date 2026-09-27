FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY apps/banking-core/pyproject.toml ./apps/banking-core/pyproject.toml

RUN uv sync --frozen --no-install-project --no-dev --package banking-core

COPY apps/banking-core/src ./apps/banking-core/src

RUN uv sync --frozen --no-dev --package banking-core && uv cache clean

RUN useradd -m -u 1000 appuser

USER appuser

EXPOSE 8081

CMD ["uvicorn", "banking_core.main:app", "--host", "0.0.0.0", "--port", "8081"]
