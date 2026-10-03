# Weights-only seed image for the encoder's fine-tuned decision model (ADR-0014, App. A).
#
# Built once per trained model by `make encoder-weights-image`, with the model
# directory itself as the build context (so the repository's .dockerignore, which
# keeps weights out of every other image, does not apply here). It holds data only:
# no shell, no runtime. apps/encoder/Dockerfile copies it in by digest, so rebuilding
# the encoder never retrains or re-downloads the model.
#
# Before building, `make encoder-weights-image` runs `python -m encoder.weights verify`
# on the directory: only the manifest's allowlisted files (safetensors weights,
# tokenizer, config, manifest) can end up in this public image.
FROM scratch

ARG MODEL_NAME
ARG REVISION_LABEL
ARG WEIGHTS_SHA256
ARG SOURCE=https://github.com/Nekobus-Bo/factored-hackathon-2026-Nekobus

LABEL org.opencontainers.image.title="pattern_blue encoder weights: ${MODEL_NAME}" \
      org.opencontainers.image.description="Fine-tuned decision model weights (ADR-0014); data only" \
      org.opencontainers.image.source="${SOURCE}" \
      org.opencontainers.image.revision="${REVISION_LABEL}" \
      dev.pattern-blue.weights-sha256="${WEIGHTS_SHA256}"

COPY . /
