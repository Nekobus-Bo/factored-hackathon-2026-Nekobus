"""Dataset loading utilities for the Factored ("Banco LATAM") dataset."""

from __future__ import annotations

import glob
from pathlib import Path

import polars as pl

ALL_TABLES: tuple[str, ...] = (
    "customers",
    "products",
    "branches",
    "service_agents",
    "daily_exchange_rates",
    "call_transcripts",
    "call_center_interactions",
    "complaints",
    "transactions",
    "satisfaction_surveys",
)

PARTITIONED_TABLES: frozenset[str] = frozenset(
    {
        "call_transcripts",
        "call_center_interactions",
        "complaints",
        "transactions",
        "satisfaction_surveys",
    }
)


def clean_column_names(df: pl.DataFrame) -> pl.DataFrame:
    """Strip UTF-8 BOM prefix from DataFrame column names."""
    return df.rename({c: c.lstrip("\ufeff") for c in df.columns})


def clean_lazy_column_names(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Strip UTF-8 BOM prefix from LazyFrame column names."""
    schema = lf.collect_schema()
    rename_map = {
        c: c.lstrip("\ufeff") for c in schema.names() if c.startswith("\ufeff")
    }
    if rename_map:
        return lf.rename(rename_map)
    return lf


def load_table(
    data_dir: Path,
    table_name: str,
    cache_dir: Path | None = None,
) -> pl.DataFrame:
    """Load a dataset table into an eager polars DataFrame.

    Checks cache_dir first if provided. Otherwise reads raw CSV(s) from data_dir.
    """
    if cache_dir is not None:
        parquet_path = cache_dir / f"{table_name}.parquet"
        if parquet_path.exists():
            return clean_column_names(pl.read_parquet(parquet_path))

    csv_single = data_dir / f"{table_name}.csv"
    if csv_single.exists():
        df = pl.read_csv(csv_single, infer_schema_length=0, encoding="utf8-lossy")
        return clean_column_names(df)

    part_dir = data_dir / table_name
    if part_dir.exists():
        glob_pattern = str(part_dir / "**" / "*.csv")
        csv_files = sorted(glob.glob(glob_pattern, recursive=True))
        if csv_files:
            lf = pl.scan_csv(glob_pattern, infer_schema_length=0, encoding="utf8-lossy")
            return clean_column_names(lf.collect())

    msg = f"Table {table_name} not found in {data_dir}"
    raise FileNotFoundError(msg)


def scan_table(
    data_dir: Path,
    table_name: str,
    cache_dir: Path | None = None,
) -> pl.LazyFrame:
    """Scan a dataset table lazily with polars.

    Useful for very large tables like transactions (4.4M rows).
    """
    if cache_dir is not None:
        parquet_path = cache_dir / f"{table_name}.parquet"
        if parquet_path.exists():
            return clean_lazy_column_names(pl.scan_parquet(parquet_path))

    csv_single = data_dir / f"{table_name}.csv"
    if csv_single.exists():
        lf = pl.scan_csv(csv_single, infer_schema_length=0, encoding="utf8-lossy")
        return clean_lazy_column_names(lf)

    part_dir = data_dir / table_name
    if part_dir.exists():
        glob_pattern = str(part_dir / "**" / "*.csv")
        lf = pl.scan_csv(glob_pattern, infer_schema_length=0, encoding="utf8-lossy")
        return clean_lazy_column_names(lf)

    msg = f"Table {table_name} not found in {data_dir}"
    raise FileNotFoundError(msg)
