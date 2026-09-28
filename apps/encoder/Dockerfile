FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# Empty: tfidf_lr baseline only. `gliner` adds PyTorch for ENCODER_BACKEND=gliner.
ARG ENCODER_EXTRAS=""

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY apps/encoder/pyproject.toml ./apps/encoder/pyproject.toml
COPY packages/contracts ./packages/contracts
COPY packages/encoder ./packages/encoder

RUN uv sync --frozen --no-install-project --no-dev --package encoder-service \
    ${ENCODER_EXTRAS:+--extra $ENCODER_EXTRAS} && uv cache clean

COPY apps/encoder/src ./apps/encoder/src

COPY data/eval/synthetic/decision.train.jsonl ./data/eval/synthetic/decision.train.jsonl

RUN uv sync --frozen --no-dev --package encoder-service \
    ${ENCODER_EXTRAS:+--extra $ENCODER_EXTRAS} && uv cache clean

# Model weights are never baked in: HF_HOME is a volume filled by `make warmup`.
ENV HF_HOME=/models/hf

RUN useradd -m -u 1000 appuser && mkdir -p /models/hf && chown -R appuser /models

USER appuser

EXPOSE 8090

CMD ["uvicorn", "encoder_service.main:app", "--host", "0.0.0.0", "--port", "8090"]
