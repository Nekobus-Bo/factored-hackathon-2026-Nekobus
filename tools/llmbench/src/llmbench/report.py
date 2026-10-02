"""Run summaries, the per-run Markdown report and the cross-model comparison.

A run file (JSON) holds every probe and episode result with its transcript; the
summary is recomputed from it, so `compare` reads only run files.
"""

import json
import statistics
from collections import Counter, defaultdict
from typing import Any

from orchestrator.conversation.prompt import FALLBACK_MESSAGES, REPHRASE_MESSAGES
from orchestrator.conversation.tools import build_llm_tools

LANGS = ("es", "pt", "en")
BLOCKING_UNSAFE = ("U1", "U2", "U6", "U7")
_CANNED = set(FALLBACK_MESSAGES.values()) | set(REPHRASE_MESSAGES.values())


def model_turns(run: dict[str, Any]) -> list[dict[str, Any]]:
    """Transcript turns the model under test answered (oracle turns left out)."""
    turns = []
    for probe in run["probes"]:
        turns.extend(t for t in probe["transcript"] if not t["by_oracle"])
    for episode in run["episodes"]:
        turns.extend(episode["transcript"])
    return turns


def _rate(items: list[bool]) -> float | None:
    return sum(items) / len(items) if items else None


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{value * 100:.0f}%"


def _ms(value: float | None) -> str:
    return "–" if value is None else f"{value / 1000:.1f}s"


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[index]


def summarize(run: dict[str, Any]) -> dict[str, Any]:
    probes = [p for p in run["probes"] if not p.get("harness_error")]
    episodes = [e for e in run["episodes"] if not e.get("not_run_reason")]
    turns = model_turns(run)
    calls = [c for t in turns for c in t["llm_calls"]]
    ok_calls = [c for c in calls if not c["error"]]

    by_skill: dict[str, dict[str, list[bool]]] = defaultdict(lambda: defaultdict(list))
    for p in probes:
        by_skill[p["skill"]][p["lang"]].append(p["passed"])
        by_skill[p["skill"]]["all"].append(p["passed"])

    unsafe = Counter(code for e in episodes for code in e["unsafe_detected"])
    proposals = [tc for c in calls for tc in (c["tool_calls"] or [])]
    _, llm_names = build_llm_tools()
    unknown = sum(1 for tc in proposals if _name(tc) not in llm_names)
    unparseable = sum(1 for tc in proposals if not _parses(tc))
    completion_tokens = sum(c["completion_tokens"] for c in ok_calls)
    call_seconds = sum(c["latency_ms"] for c in ok_calls) / 1000

    return {
        "probe_pass": _rate([p["passed"] for p in probes]),
        "probe_pass_by_lang": {
            lang: _rate([p["passed"] for p in probes if p["lang"] == lang])
            for lang in LANGS
        },
        "probe_pass_by_skill": {
            skill: {k: _rate(v) for k, v in langs.items()}
            for skill, langs in sorted(by_skill.items())
        },
        "probe_harness_errors": len(run["probes"]) - len(probes),
        "episode_pass": _rate([e["passed"] for e in episodes]),
        "episode_pass_by_lang": {
            lang: _rate([e["passed"] for e in episodes if e["lang"] == lang])
            for lang in LANGS
        },
        "episodes_not_run": len(run["episodes"]) - len(episodes),
        "unsafe": dict(sorted(unsafe.items())),
        "unsafe_blocking": sum(unsafe[c] for c in BLOCKING_UNSAFE),
        "model_turns": len(turns),
        "turn_errors": sum(1 for t in turns if t["error"]),
        "canned_replies": sum(1 for t in turns if t["reply"] in _CANNED),
        "guard_hits": sum(len(t["local_rejections"]) for t in turns),
        "unknown_tools": unknown,
        "unparseable_args": unparseable,
        "llm_calls": len(calls),
        "llm_call_errors": len(calls) - len(ok_calls),
        "call_p50_ms": _percentile([c["latency_ms"] for c in ok_calls], 0.5),
        "call_p95_ms": _percentile([c["latency_ms"] for c in ok_calls], 0.95),
        "turn_p50_ms": _percentile([t["latency_ms"] for t in turns], 0.5),
        "turn_p95_ms": _percentile([t["latency_ms"] for t in turns], 0.95),
        "prompt_tokens_mean": statistics.fmean([c["prompt_tokens"] for c in ok_calls])
        if ok_calls
        else None,
        # Wall-clock: prefill included, so lower than the server's decode rate.
        "completion_tokens_per_s": completion_tokens / call_seconds
        if call_seconds
        else None,
    }


def render_run(run: dict[str, Any]) -> str:
    s = run["summary"]
    where = run["base_url"] or "provider default"
    lines = [
        f"# llmbench run: {run['label']}",
        "",
        "Sandbox bank (banking-core's control layer, in-memory data), no encoder. "
        "Evidence for choosing a model, not system evidence.",
        "",
        f"- Model: `{run['litellm_model']}` at `{where}`",
        f"- Tool routing: {'on' if run['routed'] else 'off'}; repeats: {run['repeat']}",
        f"- Started: {run['started_at']}; duration: {run['duration_s']:.0f}s",
        "",
        "## Summary",
        "",
        "| Metric | All | es | pt | en |",
        "|---|---|---|---|---|",
        "| Probes passed | "
        + _pct(s["probe_pass"])
        + " | "
        + " | ".join(_pct(s["probe_pass_by_lang"][lang]) for lang in LANGS)
        + " |",
        "| Episodes passed | "
        + _pct(s["episode_pass"])
        + " | "
        + " | ".join(_pct(s["episode_pass_by_lang"][lang]) for lang in LANGS)
        + " |",
        "",
        "| Safety and robustness | Value |",
        "|---|---|",
        f"| Unsafe outcomes detected (blocking U1/U2/U6/U7) | {s['unsafe_blocking']} |",
        f"| Unsafe outcomes by code | {s['unsafe'] or 'none'} |",
        "| Guard hits (calls the engine rejected before banking-core) | "
        f"{s['guard_hits']} |",
        f"| Unknown tool names / unparseable arguments | "
        f"{s['unknown_tools']} / {s['unparseable_args']} |",
        f"| Turn errors / canned fallback replies | "
        f"{s['turn_errors']} / {s['canned_replies']} |",
        f"| Probe prefixes that failed (bench defect) | {s['probe_harness_errors']} |",
        "",
        "| Latency and size | Value |",
        "|---|---|",
        f"| LLM call p50 / p95 | {_ms(s['call_p50_ms'])} / {_ms(s['call_p95_ms'])} |",
        f"| Model turn p50 / p95 | {_ms(s['turn_p50_ms'])} / {_ms(s['turn_p95_ms'])} |",
        f"| Prompt tokens per call (mean) | {_num(s['prompt_tokens_mean'])} |",
        f"| Completion tokens/s (wall clock) | {_num(s['completion_tokens_per_s'])} |",
        f"| LLM calls (errors) | {s['llm_calls']} ({s['llm_call_errors']}) |",
        "",
        "## Probes by skill",
        "",
        "| Skill | All | es | pt | en |",
        "|---|---|---|---|---|",
    ]
    for skill, rates in s["probe_pass_by_skill"].items():
        lines.append(
            f"| {skill} | {_pct(rates.get('all'))} | "
            + " | ".join(_pct(rates.get(lang)) for lang in LANGS)
            + " |"
        )
    lines += ["", "## Episodes", "", "| Scenario | Result | Failed checks | Unsafe |"]
    lines.append("|---|---|---|---|")
    for e in run["episodes"]:
        result = (
            "not run"
            if e.get("not_run_reason")
            else ("pass" if e["passed"] else "FAIL")
        )
        lines.append(
            f"| {e['scenario_id']} | {result} | {', '.join(e['failed_checks']) or '–'} "
            f"| {', '.join(e['unsafe_detected']) or '–'} |"
        )
    failures = [p for p in run["probes"] if not p["passed"]]
    if failures:
        lines += ["", "## Probe failures", ""]
        for p in failures:
            reason = (
                p.get("harness_error")
                or p.get("turn_error")
                or "; ".join(
                    f"{c['name']}: {c['detail']}"
                    for c in p["checks"]
                    if not c["passed"]
                )
            )
            lines.append(f"- `{p['id']}`: {reason}")
    return "\n".join(lines) + "\n"


def render_compare(runs: list[dict[str, Any]]) -> str:
    summaries = [(r["label"], r["summary"]) for r in runs]
    lines = [
        "# llmbench comparison",
        "",
        "Sandbox bank (banking-core's control layer, in-memory data), no encoder. "
        "Evidence for choosing a model, not system evidence.",
        "",
        "| Model | Probes | es | pt | en | Episodes | Blocking unsafe | Guard hits "
        "| Call p50 / p95 | Turn p95 | Tok/s |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for label, s in summaries:
        lines.append(
            f"| {label} | {_pct(s['probe_pass'])} | "
            + " | ".join(_pct(s["probe_pass_by_lang"][lang]) for lang in LANGS)
            + f" | {_pct(s['episode_pass'])} | {s['unsafe_blocking']} "
            f"| {s['guard_hits']} | {_ms(s['call_p50_ms'])} / {_ms(s['call_p95_ms'])} "
            f"| {_ms(s['turn_p95_ms'])} | {_num(s['completion_tokens_per_s'])} |"
        )
    skills = sorted({k for _, s in summaries for k in s["probe_pass_by_skill"]})
    lines += [
        "",
        "## Probes by skill (all languages)",
        "",
        "| Skill | " + " | ".join(label for label, _ in summaries) + " |",
        "|---|" + "---|" * len(summaries),
    ]
    for skill in skills:
        lines.append(
            f"| {skill} | "
            + " | ".join(
                _pct(s["probe_pass_by_skill"].get(skill, {}).get("all"))
                for _, s in summaries
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _num(value: float | None) -> str:
    return "–" if value is None else f"{value:.0f}"


def _name(tool_call: dict[str, Any]) -> str:
    fn = tool_call.get("function")
    return str(fn.get("name") or "") if isinstance(fn, dict) else ""


def _parses(tool_call: dict[str, Any]) -> bool:
    fn = tool_call.get("function")
    raw = fn.get("arguments") if isinstance(fn, dict) else None
    if raw is None or isinstance(raw, dict):
        return True
    try:
        return isinstance(json.loads(raw), dict) if str(raw).strip() else True
    except ValueError:
        return False
