"""Tests for evaluation report rendering and FakeSystem output guard."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import ClassVar

import pytest

from evalrunner.guard import guard_fakesystem_output, is_real_system
from evalrunner.models import CheckDetail, ScenarioRunResult, TurnResult, UnsafeOutcome
from evalrunner.report import render_evaluation_report

REPO_ROOT = Path(__file__).resolve().parents[3]


class MarkedSystem:
    """Declares itself real the way ProposedSystem does, with nothing else to it."""

    name = "marked"
    real_system: ClassVar[bool] = True


class UnmarkedSystem:
    """Named like the real one but without the marker: a fake."""

    name = "proposed"


def test_guard_fakesystem_output_raises_for_reports_dir():
    with tempfile.TemporaryDirectory() as fake_repo:
        repo_path = Path(fake_repo)
        (repo_path / "reports").mkdir()

        # Target directly in reports/
        with pytest.raises(
            ValueError, match="Refusing to write fake evaluation report"
        ):
            guard_fakesystem_output(
                system_name="FakeSystem",
                out_path=repo_path / "reports" / "eval.md",
                repo_root=repo_path,
            )

        # Target in subfolder of reports/
        with pytest.raises(
            ValueError, match="Refusing to write fake evaluation report"
        ):
            guard_fakesystem_output(
                system_name="FakeSystem",
                out_path=repo_path / "reports" / "sub" / "eval.md",
                repo_root=repo_path,
            )


def test_guard_fakesystem_output_allows_tmp():
    with tempfile.TemporaryDirectory() as fake_repo:
        repo_path = Path(fake_repo)
        (repo_path / "reports").mkdir()

        # Non-reports destination passes
        guard_fakesystem_output(
            system_name="FakeSystem",
            out_path="/tmp/eval-report.md",
            repo_root=repo_path,
        )

        # Path like /tmp/reports/custom outside repo passes
        guard_fakesystem_output(
            system_name="FakeSystem",
            out_path="/tmp/reports/custom.md",
            repo_root=repo_path,
        )


def test_guard_non_fakesystem_allows_reports():
    with tempfile.TemporaryDirectory() as fake_repo:
        repo_path = Path(fake_repo)
        (repo_path / "reports").mkdir()

        # A system that declares itself real is allowed to write into reports/
        guard_fakesystem_output(
            system=MarkedSystem(),
            out_path=repo_path / "reports" / "eval.md",
            repo_root=repo_path,
        )


def test_guard_from_eval_runner_relative_reports():
    # When running from eval/runner directory with --out ../../reports/x.md
    runner_dir = Path(__file__).resolve().parent.parent  # eval/runner
    repo_root = runner_dir.parent.parent  # repo root
    rel_out = Path("../../reports/test_eval.md")

    # Resolving from runner_dir should target repo_root/reports/
    target_abs = (runner_dir / rel_out).resolve()
    assert target_abs == repo_root / "reports" / "test_eval.md"

    # FakeSystem must be blocked by default repo_root resolution
    with pytest.raises(ValueError, match="Refusing to write fake evaluation report"):
        guard_fakesystem_output(
            system_name="FakeSystem",
            out_path=target_abs,
            repo_root=None,
        )

    # A system that declares itself real is allowed
    guard_fakesystem_output(
        system=MarkedSystem(),
        out_path=target_abs,
        repo_root=None,
    )


def test_guard_rejects_fake_system_named_proposed():
    # A fake named "proposed" must fail when targeting reports/
    try:
        from fake_system import FakeSystem
    except ImportError:
        from .fake_system import FakeSystem

    fake = FakeSystem(name="proposed")
    repo_root = Path(__file__).resolve().parents[3]
    target_abs = repo_root / "reports" / "eval.md"

    with pytest.raises(ValueError, match="Refusing to write fake evaluation report"):
        guard_fakesystem_output(system=fake, out_path=target_abs)


def test_only_a_class_level_marker_makes_a_system_real():
    class InstanceMarked:
        name = "proposed"

        def __init__(self) -> None:
            self.real_system = True

    assert is_real_system(MarkedSystem())
    assert is_real_system(MarkedSystem)
    assert not is_real_system(UnmarkedSystem())
    assert not is_real_system(InstanceMarked())
    assert not is_real_system("proposed")
    assert not is_real_system(None)

    with pytest.raises(ValueError, match="Refusing to write fake evaluation report"):
        guard_fakesystem_output(
            system=UnmarkedSystem(), out_path=REPO_ROOT / "reports" / "eval.md"
        )


def test_run_evaluation_default_path_refuses_a_fake(monkeypatch):
    # The default report path is reports/eval-<date>.md relative to the repo root.
    from evalrunner import runner

    try:
        from fake_system import FakeSystem
    except ImportError:
        from .fake_system import FakeSystem

    rendered: list[dict] = []

    def fake_render(**kwargs):
        rendered.append(kwargs)
        return kwargs["out_path"]

    monkeypatch.setattr(runner, "render_evaluation_report", fake_render)
    monkeypatch.chdir(REPO_ROOT)

    with pytest.raises(ValueError, match="Refusing to write fake evaluation report"):
        runner.run_evaluation(system=FakeSystem(name="proposed"), scenarios=[])
    assert rendered == []


def test_run_evaluation_enforces_guard():
    # Calling run_evaluation with FakeSystem targeting reports must fail
    try:
        from fake_system import FakeSystem
    except ImportError:
        from .fake_system import FakeSystem

    from evalrunner.runner import run_evaluation

    repo_root = Path(__file__).resolve().parents[3]
    reports_out = repo_root / "reports" / "should_fail.md"

    with pytest.raises(ValueError, match="Refusing to write fake evaluation report"):
        run_evaluation(
            system=FakeSystem(name="FakeSystem"),
            scenarios=[],
            out_path=reports_out,
        )


def test_render_evaluation_report():
    results = [
        ScenarioRunResult(
            scenario_id="happy_001_es",
            lang="es",
            group="happy_path",
            passed=True,
            checks=[
                CheckDetail(
                    check_name="final_verification_state",
                    passed=True,
                    expected="VERIFIED",
                    actual="VERIFIED",
                )
            ],
            unsafe_outcomes=[
                UnsafeOutcome(code="U1", detected=False, status="clear"),
                UnsafeOutcome(code="U4", detected=False, status="clear"),
            ],
            turns=[TurnResult(latency_ms=120.0, cost_usd=0.002, tokens_used=150)],
            p50_latency_ms=120.0,
            p95_latency_ms=120.0,
            total_cost_usd=0.002,
            total_tokens=150,
            automated_resolution=True,
        ),
        ScenarioRunResult(
            scenario_id="adv_001_pt",
            lang="pt",
            group="adversarial",
            passed=False,
            checks=[
                CheckDetail(
                    check_name="tools_forbidden",
                    passed=False,
                    expected="none",
                    actual=["card.block"],
                )
            ],
            unsafe_outcomes=[
                UnsafeOutcome(
                    code="U1",
                    detected=True,
                    status="detected",
                    description="Executed in ANONYMOUS",
                ),
                UnsafeOutcome(code="U2", detected=False, status="needs_human_review"),
            ],
            turns=[TurnResult(latency_ms=250.0, cost_usd=0.004, tokens_used=300)],
            p50_latency_ms=250.0,
            p95_latency_ms=250.0,
            total_cost_usd=0.004,
            total_tokens=300,
        ),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        report_file = Path(tmpdir) / "eval-test.md"
        render_evaluation_report(
            system_name="FakeSystem",
            results=results,
            out_path=report_file,
        )

        assert report_file.is_file()
        content = report_file.read_text(encoding="utf-8")

        # Check main document sections per docs/evaluation.md §2
        assert "# System Evaluation Report" in content
        assert "## 1. System Outcome Metrics by Language" in content
        assert "| **es** |" in content
        assert "| **pt** |" in content
        assert (
            "| **en** | no data |" in content
        )  # handles languages with no data gracefully

        assert "## 2. Unsafe Outcomes Taxonomy (U1–U8)" in content
        assert "| `U1` |" in content
        assert "VIOLATION (1)" in content
        assert "Needs human review" in content

        assert "## 3. Scenario Results Detail" in content
        assert "`happy_001_es`" in content
        assert "`adv_001_pt`" in content
