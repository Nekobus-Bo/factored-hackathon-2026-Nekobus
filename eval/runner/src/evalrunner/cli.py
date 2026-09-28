"""CLI entry point for evaluation runner."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from evalrunner.loader import load_scenarios_from_directory
from evalrunner.models import Scenario
from evalrunner.runner import run_evaluation
from evalrunner.systems.evidence import EvidenceSource
from evalrunner.systems.proposed import ProposedConfig


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
        "--dry-run",
        action="store_true",
        help=(
            "List which scenarios are runnable against the system and why the "
            "others are not, without running them (proposed only)"
        ),
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
    elif args.system == "proposed":
        from evalrunner.systems.evidence import PostgresEvidence
        from evalrunner.systems.proposed import ProposedSystem

        config = ProposedConfig.from_env()
        if args.dry_run:
            evidence = (
                PostgresEvidence(config.readonly_dsn) if config.readonly_dsn else None
            )
            return _dry_run(scenarios, evidence, config)
        if not config.readonly_dsn:
            print(
                "Error: EVAL_READONLY_DSN is required to run the proposed system "
                "(read-only access to banking-core evidence).",
                file=sys.stderr,
            )
            return 2
        system = ProposedSystem(config, PostgresEvidence(config.readonly_dsn))
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
    not_run_count = sum(1 for r in results if r.not_run_reason is not None)
    print(
        f"Evaluation complete: {passed_count}/{len(results)} scenarios passed, "
        f"{not_run_count} not run."
    )
    if report_file:
        print(f"Report written to: {report_file}")

    return 0 if passed_count == len(results) else 1


def _probe_admin(config: ProposedConfig) -> tuple[bool, str]:
    import httpx

    from evalrunner.systems.admin import AdminError, HttpAdminApi

    api = HttpAdminApi(
        config.banking_core_url, config.admin_token, httpx.Client(timeout=3.0)
    )
    try:
        available = api.available()
    except AdminError as exc:
        return False, f"error ({exc})"
    return available, "available" if available else "missing or unreachable"


def _dry_run(
    scenarios: list[Scenario],
    evidence: EvidenceSource | None,
    config: ProposedConfig,
) -> int:
    """Print runnability per scenario. Always exits 0: it is a report."""
    from evalrunner.systems.faults import NoFaultInjector
    from evalrunner.systems.setup import assess

    admin_available, admin_label = _probe_admin(config)
    mode = "live" if evidence is not None else "offline (EVAL_READONLY_DSN unset)"
    print(f"Dry run against 'proposed' — evidence: {mode}; admin API: {admin_label}")
    runnable = 0
    feasible = 0
    for scenario in scenarios:
        result = assess(
            scenario, evidence, config.replay_dir, admin_available, NoFaultInjector()
        )
        runnable += result.runnable
        feasible += not [
            b for b in result.blockers if not b.startswith("no replay recordings")
        ]
        label = "RUNNABLE" if result.runnable else "NOT RUNNABLE"
        print(f"{scenario.id:<28} {label}")
        for reason in result.blockers:
            print(f"    - {reason}")
        for note in result.notes:
            print(f"    · {note}")
    print(f"{runnable}/{len(scenarios)} scenarios runnable.")
    print(f"{feasible}/{len(scenarios)} would be runnable once replays are recorded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
