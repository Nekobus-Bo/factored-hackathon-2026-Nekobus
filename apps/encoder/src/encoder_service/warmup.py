"""Build the configured backend once, so its weights land in the model cache.

For ENCODER_BACKEND=gliner this downloads ENCODER_MODEL into HF_HOME (a volume
in compose); for tfidf_lr it only checks that the train data loads. Exits
non-zero with the reason if the backend cannot be built.
"""

import sys

from encoder_service.config import get_backend_settings
from encoder_service.model_backends import BackendConfigError, build_backend


def main() -> None:
    try:
        backend = build_backend(get_backend_settings())
    except BackendConfigError as exc:
        sys.exit(f"warmup: {exc}")
    if backend is None:
        print("warmup: ENCODER_BACKEND is unset; nothing to preload")
        return
    print(f"warmup: {backend.model_id} ready")


if __name__ == "__main__":
    main()
