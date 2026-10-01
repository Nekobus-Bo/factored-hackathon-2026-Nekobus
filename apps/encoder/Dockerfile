FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# Extras, space or comma separated. Empty: the tfidf_lr baseline and the decision
# points only. `embed` adds PyTorch and sentence-transformers for POST /v1/embed (the
# kb.search embedding model, EMBEDDING_MODEL); `gliner` adds PyTorch for
# ENCODER_BACKEND=gliner. The compose file builds with `embed`.
ARG ENCODER_EXTRAS=""

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY apps/encoder/pyproject.toml ./apps/encoder/pyproject.toml
COPY packages/contracts ./packages/contracts
COPY packages/encoder ./packages/encoder
COPY packages/retrieval ./packages/retrieval

RUN EXTRA_ARGS="$(for e in $(echo "$ENCODER_EXTRAS" | tr ',' ' '); do printf -- '--extra %s ' "$e"; done)" \
    && uv sync --frozen --no-install-project --no-dev --package encoder-service $EXTRA_ARGS \
    && uv cache clean

COPY apps/encoder/src ./apps/encoder/src

COPY data/eval/synthetic/decision.train.jsonl ./data/eval/synthetic/decision.train.jsonl

RUN EXTRA_ARGS="$(for e in $(echo "$ENCODER_EXTRAS" | tr ',' ' '); do printf -- '--extra %s ' "$e"; done)" \
    && uv sync --frozen --no-dev --package encoder-service $EXTRA_ARGS \
    && uv cache clean

# Model weights are never baked in: HF_HOME is a volume filled by `make warmup`
# (the decision backend) and `make warmup-retrieval` (the embedding model).
ENV HF_HOME=/models/hf

RUN useradd -m -u 1000 appuser && mkdir -p /models/hf && chown -R appuser /models

USER appuser

EXPOSE 8090

CMD ["uvicorn", "encoder_service.main:app", "--host", "0.0.0.0", "--port", "8090"]
