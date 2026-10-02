"""llmbench command line: serve-cmd, run, compare."""

import argparse
import asyncio
import json
import shlex
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml
from dotenv import dotenv_values

from llmbench.episodes import (
    SCENARIOS_DIR,
    SandboxSystem,
    load_episodes,
    read_episode_ids,
    run_episodes,
)
from llmbench.harness import Conversation
from llmbench.probes import PROBES_DIR, load_probes, run_probe
from llmbench.provider import BenchProvider, live_provider
from llmbench.report import render_compare, render_run, summarize

BENCH_DIR = Path("tools/llmbench")
MODELS_FILE = BENCH_DIR / "models.yaml"
EPISODES_FILE = BENCH_DIR / "episodes.txt"
RESULTS_DIR = BENCH_DIR / "results"


def load_models(path: Path = MODELS_FILE) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def serve_command(
    alias: str, config: dict[str, Any], binary: str = "llama-server"
) -> list[str]:
    models = config["models"]
    if alias not in models:
        raise SystemExit(f"unknown model {alias!r}; known: {', '.join(models)}")
    server = config["server"]
    return [
        binary,
        "-hf",
        models[alias]["hf"],
        "--alias",
        alias,
        "--host",
        str(server["host"]),
        "--port",
        str(server["port"]),
        "-c",
        str(server["ctx_size"]),
        *server.get("args", []),
        *models[alias].get("server_args", []),
    ]


def check_server(base_url: str, alias: str) -> None:
    try:
        response = httpx.get(f"{base_url}/models", timeout=5)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise SystemExit(
            f"{base_url}/models answered HTTP {exc.response.status_code}: another "
            "service holds that port. Change server.port in models.yaml"
        ) from None
    except httpx.HTTPError as exc:
        raise SystemExit(
            f"no OpenAI-compatible server at {base_url} ({type(exc).__name__}). "
            f"Start one with: make llm-bench-serve MODEL={alias}"
        ) from None
    served = [m.get("id") for m in response.json().get("data", [])]
    if alias not in served:
        raise SystemExit(
            f"the server at {base_url} serves {served}, not {alias!r}. "
            f"Restart it with: make llm-bench-serve MODEL={alias}"
        )


def hosted_api_key(env_var: str, env_file: Path = Path(".env")) -> str:
    """The hosted model's key: the environment first, then the repo's .env."""
    import os

    key = os.environ.get(env_var) or dotenv_values(env_file).get(env_var)
    if not key or key.strip() in ("", "TODO"):
        raise SystemExit(f"{env_var} is not set (environment or .env)")
    return key.strip()


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def cmd_run(args: argparse.Namespace) -> int:
    config = load_models(Path(args.models_file))
    alias = args.model
    entry = config.get("hosted", {}).get(alias)
    request_kwargs: dict[str, Any] = {}
    if entry is not None:
        # A hosted reference model: no local server, the provider's own key.
        litellm_model = entry["litellm_model"]
        base_url = args.base_url or entry.get("base_url")
        inner = live_provider(
            litellm_model,
            base_url,
            api_key=hosted_api_key(entry.get("api_key_env", "LLM_API_KEY")),
            timeout_seconds=args.timeout,
            reasoning_effort=entry.get("reasoning_effort", ""),
            max_retries=int(entry.get("max_retries", 2)),
        )
        if "temperature" in entry:
            request_kwargs["temperature"] = float(entry["temperature"])
    else:
        server = config["server"]
        base_url = args.base_url or f"http://{server['host']}:{server['port']}/v1"
        litellm_model = f"openai/{alias}"
        if not args.skip_server_check:
            check_server(base_url, alias)
        inner = live_provider(litellm_model, base_url, timeout_seconds=args.timeout)

    def make_llm(conversation: Conversation) -> BenchProvider:
        return BenchProvider(
            inner,
            llm_names=conversation.llm_names,
            allowed_tools=conversation.allowed_tools if args.route_tools else None,
            request_kwargs=request_kwargs,
        )

    probes = load_probes(Path(args.probes_dir)) if args.only != "episodes" else []
    probes = [
        p
        for p in probes
        if (not args.lang or p.lang == args.lang)
        and (not args.skill or p.skill in args.skill)
    ]
    episodes = (
        load_episodes(read_episode_ids(Path(args.episodes_file)), Path(args.scenarios))
        if args.only != "probes"
        else []
    )
    episodes = [e for e in episodes if not args.lang or e.lang == args.lang]

    label = alias + ("+routed" if args.route_tools else "")
    started = time.perf_counter()
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    loop = asyncio.new_event_loop()
    probe_results: list[dict[str, Any]] = []
    episode_results: list[dict[str, Any]] = []
    try:
        for rep in range(args.repeat):
            for i, probe in enumerate(probes, 1):
                result = loop.run_until_complete(run_probe(probe, make_llm))
                row = result.model_dump(mode="json") | {"repeat": rep}
                probe_results.append(row)
                verdict = "PASS" if result.passed else "fail"
                if result.harness_error:
                    verdict = "HARNESS"
                _log(f"[{label}] probe {i}/{len(probes)} {probe.id}: {verdict}")
            system = SandboxSystem(label, make_llm, loop)
            for i, scenario in enumerate(episodes, 1):
                ((result, session),) = run_episodes(system, [scenario])
                episode_results.append(
                    {
                        "scenario_id": result.scenario_id,
                        "lang": result.lang,
                        "group": result.group,
                        "passed": result.passed,
                        "failed_checks": [
                            c.check_name for c in result.checks if not c.passed
                        ],
                        "unsafe_detected": [
                            u.code for u in result.unsafe_outcomes if u.detected
                        ],
                        "error": result.error,
                        "not_run_reason": result.not_run_reason,
                        "transcript": [t.transcript() for t in session.records],
                        "repeat": rep,
                    }
                )
                verdict = "PASS" if result.passed else "fail"
                _log(f"[{label}] episode {i}/{len(episodes)} {scenario.id}: {verdict}")
    finally:
        loop.close()

    run = {
        "label": label,
        "model": alias,
        "litellm_model": litellm_model,
        "hosted": entry is not None,
        "request": {
            "reasoning_effort": (entry or {}).get("reasoning_effort") or None,
            "temperature": request_kwargs.get("temperature", 0.0),
        },
        "base_url": base_url,
        "routed": args.route_tools,
        "repeat": args.repeat,
        "started_at": started_at,
        "duration_s": time.perf_counter() - started,
        "filters": {"lang": args.lang, "skill": args.skill, "only": args.only},
        "probes": probe_results,
        "episodes": episode_results,
    }
    run["summary"] = summarize(run)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{started_at[:10]}-{label}"
    (out_dir / f"{stem}.json").write_text(
        json.dumps(run, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    report = render_run(run)
    (out_dir / f"{stem}.md").write_text(report, encoding="utf-8")
    print(report)
    _log(f"wrote {out_dir / stem}.json and .md")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    paths = [Path(p) for p in args.runs] or sorted(Path(args.out_dir).glob("*.json"))
    if not paths:
        raise SystemExit(f"no run files in {args.out_dir}; run `make llm-bench` first")
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    for run, path in zip(runs, paths, strict=True):
        run["summary"] = summarize(run)
        run["label"] = run.get("label") or path.stem
    table = render_compare(runs)
    if args.publish:
        target = Path("reports") / f"llm-bench-{datetime.now(UTC).date()}.md"
        target.write_text(table, encoding="utf-8")
        _log(f"wrote {target}")
    print(table)
    return 0


def cmd_serve_cmd(args: argparse.Namespace) -> int:
    config = load_models(Path(args.models_file))
    print(shlex.join(serve_command(args.model, config, args.binary)))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="llmbench", description=__doc__)
    parser.add_argument("--models-file", default=str(MODELS_FILE))
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run probes and episodes against a served model")
    run.add_argument(
        "--model", required=True, help="alias from models.yaml (local or hosted)"
    )
    run.add_argument(
        "--base-url", help="OpenAI-compatible base URL (default: models.yaml)"
    )
    run.add_argument(
        "--route-tools",
        action="store_true",
        help="offer only the tools the session state allows",
    )
    run.add_argument("--repeat", type=int, default=1)
    run.add_argument("--only", choices=["probes", "episodes"])
    run.add_argument("--lang", choices=["es", "pt", "en"])
    run.add_argument("--skill", action="append", help="probe skill (repeatable)")
    run.add_argument("--timeout", type=float, default=120.0, help="seconds per call")
    run.add_argument("--probes-dir", default=str(PROBES_DIR))
    run.add_argument("--episodes-file", default=str(EPISODES_FILE))
    run.add_argument("--scenarios", default=str(SCENARIOS_DIR))
    run.add_argument("--out-dir", default=str(RESULTS_DIR))
    run.add_argument("--skip-server-check", action="store_true")
    run.set_defaults(func=cmd_run)

    compare = sub.add_parser("compare", help="Compare run files")
    compare.add_argument("runs", nargs="*", help="run JSON files (default: all)")
    compare.add_argument("--out-dir", default=str(RESULTS_DIR))
    compare.add_argument(
        "--publish", action="store_true", help="also write reports/llm-bench-<date>.md"
    )
    compare.set_defaults(func=cmd_compare)

    serve = sub.add_parser(
        "serve-cmd", help="Print the llama-server command for a model"
    )
    serve.add_argument("--model", required=True)
    serve.add_argument("--binary", default="llama-server")
    serve.set_defaults(func=cmd_serve_cmd)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
