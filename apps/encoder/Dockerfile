# The fine-tuned decision model's weights (ADR-0014): a data-only seed image, pinned by
# digest. This line is the single source of the pin; a retrain publishes a new seed
# image (`make encoder-weights-image PUSH=1`) and changes only this digest. To build
# from a local, unpublished directory instead:
#   docker buildx build --build-context weights=packages/encoder/weights/distilbert-intent-pooled ...
ARG ENCODER_WEIGHTS_IMAGE=docker.io/paodanchacon/pattern_blue-encoder-weights@sha256:459d30a9c697e66455377700f1cd019e3b265be7bf53a53a691caf942dc17107
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

# By default Hub models are not baked in: compose mounts HF_HOME as a volume filled by
# `make warmup` (a gliner decision backend) and `make warmup-retrieval` (the embedding
# model). The fine-tuned DistilBERT above is always baked in (ADR-0014), and the Cloud
# Run image bakes the embedding model too (below).
ENV HF_HOME=/models/hf

RUN useradd -m -u 1000 appuser && mkdir -p /models/hf && chown -R appuser /models

USER appuser

# The Cloud Run image has no volume, so it bakes the embedding model in (ADR-0015): set all
# three and the build downloads exactly that revision into HF_HOME and fails unless the
# weights match the hash. Needs `embed` in ENCODER_EXTRAS and network at build time. The
# service still reads the same three variables at runtime, and banking-core checks them.
ARG EMBEDDING_MODEL=""
ARG EMBEDDING_REVISION=""
ARG EMBEDDING_WEIGHTS_SHA256=""
RUN if [ -n "$EMBEDDING_MODEL" ]; then \
        if [ -z "$EMBEDDING_REVISION" ] || [ -z "$EMBEDDING_WEIGHTS_SHA256" ]; then \
            echo "EMBEDDING_MODEL is set: EMBEDDING_REVISION and EMBEDDING_WEIGHTS_SHA256 are required" >&2; \
            exit 1; \
        fi; \
        python -m encoder_service.warmup --only embedding; \
    fi

EXPOSE 8090

CMD ["uvicorn", "encoder_service.main:app", "--host", "0.0.0.0", "--port", "8090"]
