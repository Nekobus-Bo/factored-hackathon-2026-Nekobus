FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY apps/encoder/pyproject.toml ./apps/encoder/pyproject.toml
COPY packages/contracts ./packages/contracts

RUN uv sync --frozen --no-install-project --no-dev --package encoder-service

COPY apps/encoder/src ./apps/encoder/src

RUN uv sync --frozen --no-dev --package encoder-service && uv cache clean

RUN useradd -m -u 1000 appuser

USER appuser

EXPOSE 8090

CMD ["uvicorn", "encoder_service.main:app", "--host", "0.0.0.0", "--port", "8090"]
