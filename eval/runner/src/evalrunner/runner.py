"""Evaluation runner core executing scenarios against SystemUnderTest."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from contracts.envelope import ToolResultStatus

from evalrunner.checks import evaluate_scenario_checks
from evalrunner.guard import guard_fakesystem_output
from evalrunner.models import Scenario, ScenarioRunResult, TurnResult
from evalrunner.protocol import (
    ScenarioNotRunError,
    SystemUnderTest,
    TurnFailedError,
)
from evalrunner.report import render_evaluation_report

logger = logging.getLogger(__name__)


def _compute_percentile(values: list[float], p: float) -> float:
    """Compute percentile from a list of floats."""
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    f = int(k)
    c = min(f + 1, len(s) - 1)
    d = k - f
    return s[f] + (s[c] - s[f]) * d


def _not_run(
    scenario: Scenario, reason: str, turns: list[TurnResult] | None = None
) -> ScenarioRunResult:
    return ScenarioRunResult(
        scenario_id=scenario.id,
        lang=scenario.lang,
        locale=scenario.locale,
        group=scenario.group,
        passed=False,
        turns=turns or [],
        not_run_reason=reason,
    )


def run_scenario(system: SystemUnderTest, scenario: Scenario) -> ScenarioRunResult:
    """Run a single scenario through the system under test turn by turn."""
    logger.info(
        "Running scenario %s (%s, %s)", scenario.id, scenario.lang, scenario.group
    )
    try:
        session = system.start(scenario)
    except ScenarioNotRunError as exc:
        logger.info("Scenario %s not run: %s", scenario.id, exc)
        return _not_run(scenario, str(exc))
    turn_results: list[TurnResult] = []
    turn_error: str | None = None

    try:
        for message in scenario.turns:
            result = system.send(session, message)
            turn_results.append(result)
    except ScenarioNotRunError as exc:
        logger.info("Scenario %s not run: %s", scenario.id, exc)
        return _not_run(scenario, str(exc), turn_results)
    except TurnFailedError as exc:
        # Fails the scenario, but its evidence still goes through the checks.
        logger.warning("Scenario %s turn failed: %s", scenario.id, exc)
        turn_results.append(exc.turn)
        turn_error = str(exc)
    except Exception as exc:
        logger.exception("Error executing scenario %s: %s", scenario.id, exc)
        return ScenarioRunResult(
            scenario_id=scenario.id,
            lang=scenario.lang,
            locale=scenario.locale,
            group=scenario.group,
            passed=False,
            turns=turn_results,
            error=str(exc),
        )
    finally:
        system.teardown(session)

    # Evaluate checks & safety taxonomy hooks
    checks, unsafe_outcomes = evaluate_scenario_checks(scenario, turn_results, session)

    # Determine overall pass
    all_checks_passed = all(c.passed for c in checks)
    no_unsafe_detected = not any(u.detected for u in unsafe_outcomes)
    passed = all_checks_passed and no_unsafe_detected and turn_error is None

    # Latencies
    latencies = [t.latency_ms for t in turn_results if t.latency_ms > 0]
    p50_lat = _compute_percentile(latencies, 0.50)
    p95_lat = _compute_percentile(latencies, 0.95)

    # Costs
    total_cost = sum(t.cost_usd for t in turn_results)
    total_tokens = sum(t.tokens_used for t in turn_results)

    # Outcome flags per docs/evaluation.md §2
    # 1. Automated resolution: eligible cases closed without human intervention
    # and with a verified action
    has_blocked_card = any(
        tr.tool == "card.block" and tr.status in (ToolResultStatus.OK, "ok")
        for t in turn_results
        for tr in t.tool_results
    )
    has_handoff = any(t.handoff.created for t in turn_results)
    automated_resolution = passed and has_blocked_card and not has_handoff

    # 2. Correct abstention: ambiguous / out of scope cases where system asked
    # or escalated instead of guessing
    is_abstention_case = (
        scenario.group in ("ambiguity", "out_of_scope")
        or scenario.expected.must_ask_clarification
    )
    correct_abstention = is_abstention_case and passed

    # 3. Unnecessary escalation: happy_path cases escalated without need
    unnecessary_escalation = (
        scenario.group == "happy_path"
        and has_handoff
        and scenario.expected.handoff == "forbidden"
    )

    # 4. Handoff quality: handoffs containing all 4 required elements
    handoff_check = next(
        (c for c in checks if c.check_name == "handoff_must_include"), None
    )
    handoff_quality_pass = (
        handoff_check.passed if (handoff_check and has_handoff) else None
    )

    return ScenarioRunResult(
        scenario_id=scenario.id,
        lang=scenario.lang,
        locale=scenario.locale,
        group=scenario.group,
        passed=passed,
        checks=checks,
        unsafe_outcomes=unsafe_outcomes,
        turns=turn_results,
        p50_latency_ms=p50_lat,
        p95_latency_ms=p95_lat,
        total_cost_usd=total_cost,
        total_tokens=total_tokens,
        automated_resolution=automated_resolution,
        correct_abstention=correct_abstention,
        unnecessary_escalation=unnecessary_escalation,
        handoff_quality_pass=handoff_quality_pass,
        error=turn_error,
    )


def run_evaluation(
    system: SystemUnderTest,
    scenarios: list[Scenario],
    out_path: str | Path | None = None,
) -> tuple[list[ScenarioRunResult], Path | None]:
    """Execute scenario suite against system and optionally render report."""
    if out_path is None:
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
        out_path = Path("reports") / f"eval-{date_str}.md"

    out_file = Path(out_path)

    # Enforce FakeSystem output guard
    guard_fakesystem_output(system, out_file)

    results: list[ScenarioRunResult] = []
    for sc in scenarios:
        res = run_scenario(system, sc)
        results.append(res)

    report_path = render_evaluation_report(
        system_name=system.name,
        results=[r for r in results if r.not_run_reason is None],
        out_path=out_file,
        not_run=[r for r in results if r.not_run_reason is not None],
    )

    return results, report_path
