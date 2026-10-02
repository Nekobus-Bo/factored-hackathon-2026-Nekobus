"""The CLI end to end with a stand-in model: run files, report, compare."""

import json
from pathlib import Path

from llmbench import cli
from orchestrator.llm.provider import LLMResponse

BENCH = Path(__file__).resolve().parents[1]
ROOT = BENCH.parents[1]


class PoliteModel:
    """Never calls a tool; always asks a question."""

    async def complete(self, messages, prompt_version="1.0", tools=None, **_):
        text = "Claro, ¿me puedes dar más detalles por favor?"
        return LLMResponse(
            content=text,
            masked_content=text,
            model="polite",
            recording_key="polite",
            usage={"prompt_tokens": 3000, "completion_tokens": 12},
        )


def test_serve_command_uses_the_alias_and_thinking_off():
    command = cli.serve_command("qwen3-1.7b", cli.load_models(BENCH / "models.yaml"))
    assert command[:3] == ["llama-server", "-hf", "unsloth/Qwen3-1.7B-GGUF:Q4_K_M"]
    assert command[command.index("--alias") + 1] == "qwen3-1.7b"
    assert '{"enable_thinking": false}' in command


def test_think_alias_turns_thinking_back_on_after_the_default():
    command = cli.serve_command(
        "qwen3.6-35b-a3b-think", cli.load_models(BENCH / "models.yaml")
    )
    flag = "--chat-template-kwargs"
    kwargs = [command[i + 1] for i, arg in enumerate(command) if arg == flag]
    assert kwargs == ['{"enable_thinking": false}', '{"enable_thinking": true}']
    assert "--no-mmproj" in command


def test_local_model_passes_its_temperature(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "live_provider", lambda *a, **k: PoliteModel())
    args = [
        "--models-file",
        str(BENCH / "models.yaml"),
        "run",
        "--model",
        "qwen3.6-35b-a3b-think",
        "--skip-server-check",
        "--only",
        "probes",
        "--lang",
        "en",
        "--skill",
        "clarify",
        "--probes-dir",
        str(BENCH / "probes"),
        "--out-dir",
        str(tmp_path),
    ]
    assert cli.main(args) == 0
    (run_file,) = tmp_path.glob("*.json")
    assert json.loads(run_file.read_text())["request"]["temperature"] == 0.6


def test_run_and_compare(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "live_provider", lambda *a, **k: PoliteModel())
    common = [
        "--models-file",
        str(BENCH / "models.yaml"),
    ]
    for extra in ([], ["--route-tools"]):
        assert (
            cli.main(
                [
                    *common,
                    "run",
                    "--model",
                    "granite-4.0-1b",
                    "--skip-server-check",
                    "--lang",
                    "es",
                    "--probes-dir",
                    str(BENCH / "probes"),
                    "--episodes-file",
                    str(BENCH / "episodes.txt"),
                    "--scenarios",
                    str(ROOT / "eval" / "scenarios"),
                    "--out-dir",
                    str(tmp_path),
                    *extra,
                ]
            )
            == 0
        )
    runs = sorted(tmp_path.glob("*.json"))
    assert len(runs) == 2
    run = json.loads(runs[0].read_text())
    assert len(run["probes"]) == 14 and len(run["episodes"]) == 7
    summary = run["summary"]
    # Asking a question is right for clarify and no_guess_card, wrong elsewhere.
    assert summary["probe_pass_by_skill"]["clarify"]["es"] == 1.0
    assert summary["probe_pass_by_skill"]["identify"]["es"] == 0.0
    assert summary["probe_harness_errors"] == 0
    assert summary["prompt_tokens_mean"] == 3000

    assert cli.main([*common, "compare", "--out-dir", str(tmp_path)]) == 0
    table = capsys.readouterr().out
    assert "| granite-4.0-1b |" in table and "| granite-4.0-1b+routed |" in table


def test_hosted_model_skips_the_server_and_passes_its_request_settings(
    tmp_path, monkeypatch
):
    built = {}

    def fake_live_provider(model, base_url, **kwargs):
        built.update(model=model, base_url=base_url, **kwargs)
        return PoliteModel()

    def no_server(*_):
        raise AssertionError("a hosted model needs no local server")

    monkeypatch.setattr(cli, "live_provider", fake_live_provider)
    monkeypatch.setattr(cli, "check_server", no_server)
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    args = [
        "--models-file",
        str(BENCH / "models.yaml"),
        "run",
        "--model",
        "gpt-6.1-sol",
        "--only",
        "probes",
        "--lang",
        "en",
        "--skill",
        "clarify",
        "--probes-dir",
        str(BENCH / "probes"),
        "--out-dir",
        str(tmp_path),
    ]
    assert cli.main(args) == 0
    assert built["model"] == "openai/gpt-6.1-sol" and built["base_url"] is None
    assert built["api_key"] == "sk-test" and built["reasoning_effort"] == "low"
    (run_file,) = tmp_path.glob("*.json")
    run = json.loads(run_file.read_text())
    assert run["hosted"] is True
    assert run["request"] == {"reasoning_effort": "low", "temperature": 1.0}


def test_hosted_model_without_a_key_fails_explicitly(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    try:
        cli.hosted_api_key("LLM_API_KEY")
    except SystemExit as exc:
        assert "LLM_API_KEY is not set" in str(exc)
    else:
        raise AssertionError("expected SystemExit")
