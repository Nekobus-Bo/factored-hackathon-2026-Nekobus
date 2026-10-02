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
    assert len(run["probes"]) == 10 and len(run["episodes"]) == 6
    summary = run["summary"]
    # Asking a question is right for clarify and no_guess_card, wrong elsewhere.
    assert summary["probe_pass_by_skill"]["clarify"]["es"] == 1.0
    assert summary["probe_pass_by_skill"]["identify"]["es"] == 0.0
    assert summary["probe_harness_errors"] == 0
    assert summary["prompt_tokens_mean"] == 3000

    assert cli.main([*common, "compare", "--out-dir", str(tmp_path)]) == 0
    table = capsys.readouterr().out
    assert "| granite-4.0-1b |" in table and "| granite-4.0-1b+routed |" in table
