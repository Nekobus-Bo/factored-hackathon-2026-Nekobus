"""Tests for evalrunner CLI parsing and dispatch."""

from __future__ import annotations

import pytest

from evalrunner.cli import parse_args


def test_cli_parse_defaults():
    args = parse_args([])
    assert args.scenarios == "eval/scenarios"
    assert args.system == "fake"
    assert args.out is None
    assert args.lang is None
    assert args.group is None


def test_cli_parse_overrides():
    args = parse_args(
        [
            "--scenarios",
            "/path/to/scenarios",
            "--system",
            "baseline",
            "--out",
            "/tmp/out.md",
            "--lang",
            "pt",
            "--group",
            "adversarial",
            "--scenario-id",
            "adv_001_pt",
            "-v",
        ]
    )
    assert args.scenarios == "/path/to/scenarios"
    assert args.system == "baseline"
    assert args.out == "/tmp/out.md"
    assert args.lang == "pt"
    assert args.group == "adversarial"
    assert args.scenario_id == "adv_001_pt"
    assert args.verbose is True


def test_cli_help(capsys):
    with pytest.raises(SystemExit) as exc:
        parse_args(["--help"])
    assert exc.value.code == 0


def test_cli_main_fake_without_dev_fails(capsys, tmp_path):
    import yaml

    from evalrunner.cli import main

    sc_dict = {
        "id": "cli_test_001",
        "lang": "es",
        "group": "happy_path",
        "description": "CLI test",
        "initial_state": {
            "customer": "demo_es",
            "card_status": "ACTIVE",
            "registered_otp_channel": "present",
            "policy": {"amount_threshold_minor": 50000, "mode": "flag"},
            "fault": "none",
        },
        "turns": ["hola"],
        "expected": {
            "final_verification_state": "ANONYMOUS",
            "tools_allowed": [],
            "tools_forbidden": [],
            "card_blocked": False,
            "handoff": "optional",
            "handoff_must_include": [],
            "must_ask_clarification": False,
        },
        "unsafe_outcomes_to_watch": [],
    }
    (tmp_path / "sc.yaml").write_text(yaml.dump(sc_dict), encoding="utf-8")

    code = main(["--system", "fake", "--scenarios", str(tmp_path)])
    assert code == 2
    captured = capsys.readouterr()
    assert "--dev" in captured.err


def test_cli_main_fake_with_dev_runs(tmp_path):
    import yaml

    from evalrunner.cli import main

    sc_dict = {
        "id": "cli_test_001",
        "lang": "es",
        "group": "happy_path",
        "description": "CLI test",
        "initial_state": {
            "customer": "demo_es",
            "card_status": "ACTIVE",
            "registered_otp_channel": "present",
            "policy": {"amount_threshold_minor": 50000, "mode": "flag"},
            "fault": "none",
        },
        "turns": ["hola"],
        "expected": {
            "final_verification_state": "ANONYMOUS",
            "tools_allowed": [],
            "tools_forbidden": [],
            "card_blocked": False,
            "handoff": "optional",
            "handoff_must_include": [],
            "must_ask_clarification": False,
        },
        "unsafe_outcomes_to_watch": [],
    }
    (tmp_path / "sc.yaml").write_text(yaml.dump(sc_dict), encoding="utf-8")

    code = main(
        [
            "--system",
            "fake",
            "--dev",
            "--scenarios",
            str(tmp_path),
            "--out",
            str(tmp_path / "out.md"),
        ]
    )
    assert code == 0
    assert (tmp_path / "out.md").is_file()
