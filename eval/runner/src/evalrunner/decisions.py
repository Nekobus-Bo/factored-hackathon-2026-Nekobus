"""The "Decision points" section of the evaluation report (ADR-0012, Appendix G).

The input is what the orchestrator's eval hook says each turn's decision points
decided and what their effects did or, in `shadow`, would have done. It is
untrusted-side evidence, like the masked outbound messages, so it feeds this
section and never a pass/fail check. Everything is counted per language, with
counts and a Wilson interval (docs/evaluation.md), and nothing is inferred: a
system that reports no decision records gets a section that says so.

What this section cannot say: whether a decision was *right*. Precision at the
threshold, with its Wilson bound, comes from the calibration reports; here are
coverage, abstention, unavailability, and for the gate and the selects how often
they would have changed the outcome.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from evalrunner.models import EffectEvidence, ScenarioRunResult

WILSON_Z = 1.96


def wilson_interval(successes: int, total: int) -> tuple[float, float] | None:
    """95% Wilson score interval for a proportion; None when nothing was counted."""
    if total <= 0:
        return None
    p = successes / total
    z2 = WILSON_Z**2
    centre = (p + z2 / (2 * total)) / (1 + z2 / total)
    margin = (WILSON_Z * math.sqrt(p * (1 - p) / total + z2 / (4 * total**2))) / (
        1 + z2 / total
    )
    return max(0.0, centre - margin), min(1.0, centre + margin)


def proportion(successes: int, total: int) -> str:
    """`57.1% (8/14) [32.6, 78.6]`, or `n/a`."""
    interval = wilson_interval(successes, total)
    if interval is None:
        return "n/a"
    low, high = interval
    return (
        f"{successes / total * 100:.1f}% ({successes}/{total}) "
        f"[{low * 100:.1f}, {high * 100:.1f}]"
    )


@dataclass
class DpCounts:
    """One decision point, one language: what it did over the turns it was asked."""

    dp_id: str
    effect: str = ""
    modes: set[str] = field(default_factory=set)
    turns: int = 0
    decided: int = 0
    abstained: int = 0
    unavailable: int = 0
    other: int = 0  # infeasible or off
    labels: Counter[str] = field(default_factory=Counter)
    reasons: Counter[str] = field(default_factory=Counter)


@dataclass
class GateCounts:
    """A gate over the proposals of its write, one language."""

    dp_id: str
    tool: str = ""
    modes: set[str] = field(default_factory=set)
    proposals: int = 0  # a write reached the gate: withheld or released
    would_withhold: int = 0  # shadow: it would have waited for a question
    withheld: int = 0  # enforce: it did
    released: int = 0  # consent was already there
    consent: Counter[str] = field(default_factory=Counter)  # by source
    revoked: int = 0
    expired: int = 0
    scenarios_with_withhold: int = 0  # scenarios with a withheld or would-withhold


@dataclass
class SelectCounts:
    """A select over the calls to its tool, one language (one row per argument)."""

    dp_id: str
    tool: str = ""
    arg: str = ""
    modes: set[str] = field(default_factory=set)
    evaluated: int = 0
    no_decision: int = 0  # nothing decided, or the call was left as the LLM made it
    agree: int = 0
    would_override: int = 0
    applied: int = 0


@dataclass
class LanguageSummary:
    lang: str
    scenarios: int = 0  # scenarios of this language that reported any decision
    turns: int = 0  # turns that reported any decision
    unreadable: int = 0
    dps: dict[str, DpCounts] = field(default_factory=dict)
    gates: dict[str, GateCounts] = field(default_factory=dict)
    selects: dict[tuple[str, str], SelectCounts] = field(default_factory=dict)

    @property
    def has_evidence(self) -> bool:
        return self.turns > 0


def summarize(
    results: list[ScenarioRunResult],
    languages: tuple[str, ...] = ("es", "pt", "en"),
) -> dict[str, LanguageSummary]:
    """Count the decision records of every scenario, per language."""
    summaries = {lang: LanguageSummary(lang) for lang in languages}
    for result in results:
        summary = summaries.get(result.lang)
        if summary is None:
            continue
        withheld_here: set[str] = set()
        reported = False
        for turn in result.turns:
            summary.unreadable += turn.decisions_unreadable
            if turn.decisions or turn.effects:
                summary.turns += 1
                reported = True
            for d in turn.decisions:
                counts = summary.dps.setdefault(d.dp_id, DpCounts(d.dp_id))
                counts.effect = d.effect or counts.effect
                counts.modes.add(d.mode)
                counts.turns += 1
                if d.outcome == "decided":
                    counts.decided += 1
                    counts.labels[d.label or "?"] += 1
                elif d.outcome == "abstained":
                    counts.abstained += 1
                elif d.outcome == "unavailable":
                    counts.unavailable += 1
                    counts.reasons[d.unavailable_reason or "unspecified"] += 1
                else:
                    counts.other += 1
            for e in turn.effects:
                if e.effect == "gate":
                    _count_gate(summary, e, withheld_here)
                elif e.effect == "select":
                    _count_select(summary, e)
        if reported:
            summary.scenarios += 1
        for dp_id in withheld_here:
            summary.gates[dp_id].scenarios_with_withhold += 1
    return summaries


def _count_gate(
    summary: LanguageSummary, effect: EffectEvidence, withheld_here: set[str]
) -> None:
    gate = summary.gates.setdefault(effect.dp_id, GateCounts(effect.dp_id))
    gate.tool = effect.tool or gate.tool
    gate.modes.add(effect.mode)
    event = effect.detail.get("event")
    if event == "withheld":
        gate.proposals += 1
        withheld_here.add(effect.dp_id)
        if effect.applied:
            gate.withheld += 1
        elif effect.would_apply:
            gate.would_withhold += 1
    elif event == "released":
        gate.proposals += 1
        gate.released += 1
    elif event == "consent_granted":
        gate.consent[str(effect.detail.get("consent_source") or "?")] += 1
    elif event == "consent_revoked":
        gate.revoked += 1
    elif event in ("consent_expired", "question_expired"):
        gate.expired += 1


def _count_select(summary: LanguageSummary, effect: EffectEvidence) -> None:
    arg = str(effect.detail.get("arg") or "?")
    select = summary.selects.setdefault(
        (effect.dp_id, arg), SelectCounts(effect.dp_id, arg=arg)
    )
    select.tool = effect.tool or select.tool
    select.modes.add(effect.mode)
    select.evaluated += 1
    dp_value = effect.detail.get("dp_value")
    if dp_value is None:
        select.no_decision += 1
    elif dp_value == effect.detail.get("llm_value"):
        select.agree += 1
    if effect.would_apply:
        select.would_override += 1
    if effect.applied:
        select.applied += 1


# ------------------------------------------------------------------ rendering


def render_section(
    results: list[ScenarioRunResult],
    number: int,
    languages: tuple[str, ...] = ("es", "pt", "en"),
) -> list[str]:
    """The report lines of the section, ready to join with newlines."""
    summaries = summarize(results, languages)
    lines = [f"## {number}. Decision Points by Language (ADR-0012)", ""]
    if not any(s.has_evidence for s in summaries.values()):
        lines += [
            "No decision-point evidence: the system under test reported no decision "
            "records (the baseline does not, and an orchestrator without decision "
            "points does not either). Nothing is inferred.",
            "",
        ]
        return lines

    versions = sorted(
        {
            d.config_version
            for r in results
            for t in r.turns
            for d in t.decisions
            if d.config_version
        }
    )
    lines += [
        "Read from the orchestrator's eval hook: untrusted-side evidence, counted "
        "and never checked. Coverage is decided ÷ turns asked, with a Wilson 95% "
        "interval. In `shadow` an effect changes nothing: *would withhold* and "
        "*would override* are what `enforce` would have done. Whether a decision "
        "was right (precision at its threshold, with its Wilson bound) comes from "
        "the calibration reports, not from here.",
        "",
        "- **Calibration artifact (`config_version`):** "
        + (", ".join(f"`{v}`" for v in versions) if versions else "none reported"),
        "",
    ]
    for lang in languages:
        lines += _render_language(summaries[lang])
    return lines


def _render_language(summary: LanguageSummary) -> list[str]:
    lines = [f"### {summary.lang}", ""]
    if not summary.has_evidence:
        return [*lines, "no data", ""]
    lines += [
        f"{summary.scenarios} scenario(s) and {summary.turns} turn(s) reported "
        "decisions.",
        "",
        "| Decision point | Effect | Mode | Turns | Decided | Abstained | "
        "Unavailable | Infeasible / off | Coverage (95% CI) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for c in summary.dps.values():
        lines.append(
            f"| `{c.dp_id}` | {c.effect or '-'} | {_modes(c.modes)} | {c.turns} | "
            f"{c.decided} | {c.abstained} | {c.unavailable} | {c.other} | "
            f"{proportion(c.decided, c.turns)} |"
        )
    lines.append("")

    reasons = [
        f"`{c.dp_id}`: "
        + ", ".join(f"{why} ×{n}" for why, n in sorted(c.reasons.items()))
        for c in summary.dps.values()
        if c.reasons
    ]
    if reasons:
        lines += ["Unavailable because: " + "; ".join(reasons) + ".", ""]

    for gate in summary.gates.values():
        lines += _render_gate(summary, gate)
    if summary.selects:
        lines += [
            "Selects (an enum argument of a call the LLM proposed):",
            "",
            "| Select | Tool.arg | Mode | Calls | No decision | Agrees with the LLM "
            "| Would override | Overridden |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for s in summary.selects.values():
            decided = s.evaluated - s.no_decision
            lines.append(
                f"| `{s.dp_id}` | `{s.tool}.{s.arg}` | {_modes(s.modes)} | "
                f"{s.evaluated} | {s.no_decision} | {proportion(s.agree, decided)} | "
                f"{s.would_override} | {s.applied} |"
            )
        lines.append("")
    if summary.unreadable:
        lines += [
            f"**{summary.unreadable} decision record(s) could not be read** and are "
            "not in the counts above.",
            "",
        ]
    return lines


def _render_gate(summary: LanguageSummary, gate: GateCounts) -> list[str]:
    scenarios = f"{gate.scenarios_with_withhold}/{summary.scenarios}"
    consent = (
        ", ".join(f"{src} ×{n}" for src, n in sorted(gate.consent.items())) or "none"
    )
    return [
        f"Gate `{gate.dp_id}` on `{gate.tool}` ({_modes(gate.modes)}):",
        "",
        "| Proposals | Would withhold (shadow) | Withheld (enforce) | Released "
        "| Consent granted | Revoked | Expired | Scenarios with a withhold |",
        "|---|---|---|---|---|---|---|---|",
        f"| {gate.proposals} | {gate.would_withhold} | {gate.withheld} | "
        f"{gate.released} | {consent} | {gate.revoked} | {gate.expired} | "
        f"{scenarios} |",
        "",
    ]


def _modes(modes: set[str]) -> str:
    return ", ".join(sorted(m for m in modes if m)) or "-"
