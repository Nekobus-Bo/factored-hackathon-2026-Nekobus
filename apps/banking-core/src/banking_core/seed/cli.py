"""CLI interface for synthetic data generation, staging, and curated seeding."""

import argparse
import sys
from pathlib import Path

from banking_core.seed.curated import load_curated_data
from banking_core.seed.generator import generate_synthetic_dataset
from banking_core.seed.quality import generate_quality_report
from banking_core.seed.staging import StagingValidationError, load_and_validate_staging


def check_raw_directory(raw_dir: Path) -> None:
    """Ensure data/raw contains only README.md and synthetic/.

    Fails with an explicit pending message if external dataset is found.
    """
    if not raw_dir.exists():
        return

    allowed = {"readme.md", "synthetic", ".gitkeep", ".gitignore"}
    unexpected_entries = [
        item.name
        for item in raw_dir.iterdir()
        if not item.name.startswith(".") and item.name.lower() not in allowed
    ]

    if unexpected_entries:
        raise RuntimeError(
            "organization dataset mapping is not implemented yet (pending)"
        )


def run_seed(raw_dir: Path, force: bool = False) -> int:
    """Execute full seed pipeline: raw check -> generate -> staging -> curated."""
    print("Checking raw directory...")
    check_raw_directory(raw_dir)

    synthetic_dir = raw_dir / "synthetic"
    req_files = [
        "customers.jsonl",
        "accounts.jsonl",
        "cards.jsonl",
        "transactions.jsonl",
    ]
    needs_gen = not synthetic_dir.exists() or any(
        not (synthetic_dir / f).exists() for f in req_files
    )

    if needs_gen:
        print(f"Generating deterministic synthetic dataset in {synthetic_dir}...")
        gen_counts = generate_synthetic_dataset(synthetic_dir)
        print(f"Raw generated: {gen_counts}")
    else:
        print(f"Using existing synthetic raw dataset in {synthetic_dir}")

    print("Validating staging layer (docs/data.md §3)...")
    staging_dataset = load_and_validate_staging(synthetic_dir)
    print("Staging validation passed: 5/5 checks OK.")

    print("Loading curated data into PostgreSQL (encrypting PII & blind indexing)...")
    counts = load_curated_data(staging_dataset, force=force)

    print("\nSeeding completed successfully:")
    print(f"  core_bank.customer:    {counts['customer']:,}")
    print(f"  core_bank.account:     {counts['account']:,}")
    print(f"  core_bank.card:        {counts['card']:,}")
    print(f"  core_bank.transaction: {counts['transaction']:,}")
    return 0


def run_data_quality(raw_dir: Path, report_path: Path) -> int:
    """Execute staging validation and write reports/data-quality.md."""
    print("Checking raw directory...")
    check_raw_directory(raw_dir)

    synthetic_dir = raw_dir / "synthetic"
    req_files = [
        "customers.jsonl",
        "accounts.jsonl",
        "cards.jsonl",
        "transactions.jsonl",
    ]
    if not synthetic_dir.exists() or any(
        not (synthetic_dir / f).exists() for f in req_files
    ):
        print(f"Generating deterministic synthetic dataset in {synthetic_dir}...")
        generate_synthetic_dataset(synthetic_dir)

    print("Validating staging layer...")
    staging_dataset = load_and_validate_staging(synthetic_dir)

    print(f"Writing data quality report to {report_path}...")
    generate_quality_report(staging_dataset, report_path)
    print(f"Data quality report written to {report_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Banking Core Seed Pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: seed
    seed_parser = subparsers.add_parser("seed", help="Seed database from data/raw")
    seed_parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("data/raw"),
        help="Path to data/raw directory",
    )
    seed_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Force seeding even if APP_ENV=production",
    )

    # Subcommand: data-quality
    dq_parser = subparsers.add_parser(
        "data-quality", help="Generate reports/data-quality.md"
    )
    dq_parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("data/raw"),
        help="Path to data/raw directory",
    )
    dq_parser.add_argument(
        "--report-path",
        type=Path,
        default=Path("reports/data-quality.md"),
        help="Path to output report",
    )

    # Subcommand: generate
    gen_parser = subparsers.add_parser(
        "generate", help="Generate raw synthetic JSONL files only"
    )
    gen_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw/synthetic"),
        help="Output directory for synthetic JSONL",
    )
    gen_parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed",
    )

    args = parser.parse_args(argv)

    try:
        if args.command == "seed":
            return run_seed(args.raw_dir, force=args.force)
        elif args.command == "data-quality":
            return run_data_quality(args.raw_dir, args.report_path)
        elif args.command == "generate":
            counts = generate_synthetic_dataset(args.output_dir, seed=args.seed)
            print(f"Generated raw synthetic dataset: {counts}")
            return 0
        else:
            parser.print_help()
            return 1
    except StagingValidationError as e:
        print(f"STAGING VALIDATION ERROR: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"UNEXPECTED ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
