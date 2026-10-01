# The fine-tuned decision model's weights (ADR-0014): a data-only seed image, pinned by
# digest. This line is the single source of the pin; a retrain publishes a new seed
# image (`make encoder-weights-image PUSH=1`) and changes only this digest. To build
# from a local, unpublished directory instead:
#   docker buildx build --build-context weights=packages/encoder/weights/distilbert-intent-pooled ...
ARG ENCODER_WEIGHTS_IMAGE=docker.io/paodanchacon/pattern_blue-encoder-weights@sha256:65d2252019f397a3060f011d2c9fa900cbd5ceef31e4dd45cfa421e1ee982eee
FROM ${ENCODER_WEIGHTS_IMAGE} AS weights

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
# ENCODER_BACKEND=gliner; `hf` adds transformers for the fine-tuned DistilBERT
# (hf_seqcls). The compose file builds with `embed hf`.
ARG ENCODER_EXTRAS=""

WORKDIR /app

# First, so code and dependency changes never invalidate this ~0.55 GB layer. The
# registry verifies weights, manifest and label order against the artifact at startup.
COPY --from=weights / ./packages/encoder/weights/distilbert-intent-pooled/

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

# Hub models are not baked in: HF_HOME is a volume filled by `make warmup` (a gliner
# decision backend) and `make warmup-retrieval` (the embedding model). The fine-tuned
# DistilBERT above is the exception (ADR-0014).
ENV HF_HOME=/models/hf

RUN useradd -m -u 1000 appuser && mkdir -p /models/hf && chown -R appuser /models

USER appuser

EXPOSE 8090

CMD ["uvicorn", "encoder_service.main:app", "--host", "0.0.0.0", "--port", "8090"]
