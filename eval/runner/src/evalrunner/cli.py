"""CLI entry point for evaluation runner."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from evalrunner.loader import load_scenarios_from_directory
from evalrunner.runner import run_evaluation


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="evalrunner",
        description=(
            "Run Pattern Blue evaluation scenarios against a system under test "
            "and generate comparison reports."
        ),
    )
    parser.add_argument(
        "--scenarios",
        "-s",
        type=str,
        default="eval/scenarios",
        help="Path to scenarios directory (default: eval/scenarios)",
    )
    parser.add_argument(
        "--system",
        choices=["fake", "baseline", "proposed"],
        default="fake",
        help="System under test to evaluate (default: fake)",
    )
    parser.add_argument(
        "--out",
        "-o",
        type=str,
        default=None,
        help="Output markdown report path (default: reports/eval-<date>.md)",
    )
    parser.add_argument(
        "--lang",
        choices=["es", "pt", "en"],
        default=None,
        help="Filter evaluation to a specific language locale",
    )
    parser.add_argument(
        "--group",
        type=str,
        default=None,
        help="Filter evaluation to a specific scenario group",
    )
    parser.add_argument(
        "--scenario-id",
        type=str,
        default=None,
        help="Run only the specified scenario ID",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Enable development mode (allows running FakeSystem test double)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Main CLI execution."""
    args = parse_args(argv)

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    scenario_ids = [args.scenario_id] if args.scenario_id else None
    scenarios = load_scenarios_from_directory(
        args.scenarios,
        lang=args.lang,
        group=args.group,
        scenario_ids=scenario_ids,
    )

    if not scenarios:
        print(
            f"No scenarios found matching criteria in {args.scenarios}", file=sys.stderr
        )
        return 1

    # Instantiate selected system under test
    if args.system == "fake":
        if not args.dev:
            print(
                "Error: System 'fake' is only available in development mode. "
                "Specify --dev to enable FakeSystem.",
                file=sys.stderr,
            )
            return 2
        try:
            from tests.fake_system import FakeSystem
        except ImportError:
            tests_dir = Path(__file__).resolve().parent.parent.parent / "tests"
            sys.path.insert(0, str(tests_dir))
            try:
                from fake_system import FakeSystem
            except ImportError:
                print(
                    "FakeSystem is only available in test environments.",
                    file=sys.stderr,
                )
                return 2
        system = FakeSystem(name="FakeSystem")
    else:
        print(
            f"System '{args.system}' is pending implementation and not available yet.",
            file=sys.stderr,
        )
        return 2

    out_path = args.out
    if out_path is None:
        out_path = "/tmp/eval-report.md" if args.system == "fake" else None

    print(f"Running {len(scenarios)} scenarios with system '{system.name}'...")
    results, report_file = run_evaluation(system, scenarios, out_path=out_path)

    passed_count = sum(1 for r in results if r.passed)
    print(f"Evaluation complete: {passed_count}/{len(results)} scenarios passed.")
    if report_file:
        print(f"Report written to: {report_file}")

    return 0 if passed_count == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
