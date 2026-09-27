# Factored Dataset Profiler

Reproducible profiling tool for the Factored ("Banco LATAM") dataset.
Reads raw CSV tables from `data/raw/factored/` and computes aggregate statistics, schema metrics, null rates, entity relationships, language/intent distributions, and data quality indicators.

## Usage

```bash
make profile-factored
# or with a custom data directory:
make profile-factored DATA_DIR=/path/to/raw/factored
```

The default directory is resolved from the repository root. If the data directory does not exist the command exits with status 1; it never falls back to another location. A parquet cache is used only when passed explicitly with `--cache-dir`.
