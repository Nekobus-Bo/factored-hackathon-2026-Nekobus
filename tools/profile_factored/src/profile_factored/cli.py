"""CLI entrypoint for profiling the Factored dataset."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from profile_factored.profiler import run_full_profile
from profile_factored.reporter import generate_markdown_report

# tools/profile_factored/src/profile_factored/cli.py -> repository root
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DATA_DIR = REPO_ROOT / "data" / "raw" / "factored"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Profile Factored ('Banco LATAM') dataset and print aggregates."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Raw dataset directory with CSVs (default: <repo>/data/raw/factored)",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Directory with parquet tables for faster profiling (used only if given)",
    )
    parser.add_argument(
        "--markdown-out",
        type=Path,
        default=None,
        help="Optional path to write generated Markdown report",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress printing report to stdout",
    )

    args = parser.parse_args(argv)

    data_dir: Path = args.data_dir
    if not data_dir.is_dir():
        print(
            f"Error: data directory not found at {data_dir}. "
            "Place the dataset there or pass --data-dir (make: DATA_DIR=...).",
            file=sys.stderr,
        )
        return 1

    cache_dir: Path | None = args.cache_dir
    if cache_dir is not None and not cache_dir.is_dir():
        print(f"Error: cache directory not found at {cache_dir}", file=sys.stderr)
        return 1

    try:
        results = run_full_profile(data_dir=data_dir, cache_dir=cache_dir)
        report_md = generate_markdown_report(results)

        if not args.quiet:
            print(report_md)

        if args.markdown_out:
            args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
            args.markdown_out.write_text(report_md, encoding="utf-8")
            print(f"\nReport saved to: {args.markdown_out}", file=sys.stderr)

        return 0
    except Exception as e:
        print(f"Error profiling dataset: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
