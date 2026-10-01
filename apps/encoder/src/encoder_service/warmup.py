"""Build the configured backends once, so their weights land in the model cache.

    python -m encoder_service.warmup                    # everything configured
    python -m encoder_service.warmup --only embedding   # the kb.search embedding model
    python -m encoder_service.warmup --only decision    # ENCODER_BACKEND only

Decision backend: for ENCODER_BACKEND=gliner this downloads ENCODER_MODEL into
HF_HOME (a volume in compose); for tfidf_lr it only checks that the train data
loads.

Embedding model (EMBEDDING_MODEL, EMBEDDING_REVISION): downloads exactly the pinned
revision when it is not cached (the network is needed only then), verifies it, loads
it, and prints the revision and weights SHA-256 to pin. Exits non-zero with the
reason if anything cannot be built.
"""

import argparse
import sys

from encoder.pinning import ModelNotCachedError, PinError, resolve_pinned_model

from encoder_service.config import get_backend_settings, get_embedding_settings
from encoder_service.embedding import (
    build_embedding_backend,
    download_pinned,
)
from encoder_service.model_backends import BackendConfigError, build_backend


def warm_decision() -> None:
    try:
        backend = build_backend(get_backend_settings())
    except BackendConfigError as exc:
        sys.exit(f"warmup: {exc}")
    if backend is None:
        print("warmup: ENCODER_BACKEND is unset; nothing to preload")
        return
    print(f"warmup: {backend.model_id} ready")


def warm_embedding() -> None:
    settings = get_embedding_settings()
    if settings.model is None:
        print("warmup: EMBEDDING_MODEL is unset; no embedding model to preload")
        return
    try:
        try:
            resolve_pinned_model(
                settings.model,
                revision=settings.revision,
                expected_sha256=settings.weights_sha256,
            )
        except ModelNotCachedError:
            print(
                f"warmup: {settings.model}@{settings.revision} is not cached; "
                "downloading (needs network)"
            )
            download_pinned(settings)
        backend = build_embedding_backend(settings)
        resolved = resolve_pinned_model(
            settings.model,
            revision=settings.revision,
            expected_sha256=settings.weights_sha256,
        )
    except (BackendConfigError, PinError) as exc:
        sys.exit(f"warmup: {exc}")
    except Exception as exc:
        sys.exit(f"warmup: cannot fetch {settings.model}: {type(exc).__name__}")
    if backend is None or not backend.is_ready():
        sys.exit(f"warmup: {settings.model} is not ready after the download")
    print(
        f"warmup: embedding {backend.model_id}@{backend.revision} ready "
        f"(dim {backend.dim})"
    )
    if settings.weights_sha256 is None:
        print(
            "warmup: not pinned by hash yet; to pin the weights set "
            f"EMBEDDING_WEIGHTS_SHA256={resolved.weights_sha256}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", choices=("decision", "embedding"))
    args = parser.parse_args()
    if args.only != "embedding":
        warm_decision()
    if args.only != "decision":
        warm_embedding()


if __name__ == "__main__":
    main()
