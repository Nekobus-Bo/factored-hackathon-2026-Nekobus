"""Source-pluggable ingestion of delivered datasets into the staging layer."""

from banking_core.seed.ingest.mapping import available_sources, load_mapping
from banking_core.seed.ingest.pipeline import (
    options_from_env,
    run_ingest,
    staged_sources,
)

__all__ = [
    "available_sources",
    "load_mapping",
    "options_from_env",
    "run_ingest",
    "staged_sources",
]
