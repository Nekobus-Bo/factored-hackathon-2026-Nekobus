"""The decision-points calibration report (ADR-0012, Appendix F.4).

One Markdown file per run. It is the evidence behind the artifact entries the run
wrote: it states the run id, embeds each entry verbatim (``make calibration-verify``
looks for that text), and says plainly what is and is not certified.
"""

from __future__ import annotations

import os
import platform
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from calibrate.artifact import canonical_json
from calibrate.dpconfig import RunConfig
from calibrate.metrics.decision import zero_error_sample_size

if TYPE_CHECKING:
    from calibrate.dp import CandidateResult, DpResult, SplitMetrics

ECE_TARGET = 0.10
PROVISIONAL = "synthetic-provisional"


def pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.1%}"


def num(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def environment() -> str:
    try:
        import sklearn

        sk = f", scikit-learn {sklearn.__version__}"
    except ImportError:
        sk = ""
    return (
        f"{platform.system()} {platform.release()} ({platform.machine()}), "
        f"Python {platform.python_version()}{sk}, {os.cpu_count() or '?'} CPUs "
        "(host, single process; not measured under the container limits)"
    )


def _mark(ok: bool) -> str:
    return "[x]" if ok else "[ ]"


def _tau_text(entry: Any) -> str:
    if entry is None:
        return "infeasible (null)"
    if isinstance(entry, dict):
        return ", ".join(
            f"{label}: {'null' if tau is None else f'{tau:.6f}'}"
            for label, tau in entry.items()
        )
    return f"{entry:.6f}"


def _banner(results: Sequence[DpResult]) -> str:
    provenance = sorted({r.provenance for r in results})
    lines = ["> [!WARNING]"]
    if PROVISIONAL in provenance:
        lines.append(
            "> The test split is **provisional synthetic (not human)**: written by an "
            "AI agent, 10 rows per intent and language, never double-labeled. It "
            "cannot certify a precision of 0.95 (or 0.90): 22 correct of 22 accepted "
            "has a Wilson lower bound of 0.85, and 0.95 needs 73 accepted with zero "
            "errors."
        )
    lines.append(
        "> Validation shares its generating process with train, so a calibrator "
        "fitted on it is over-confident on real traffic. Thresholds here are chosen "
        "on validation only; nothing in this report is a guarantee on real customers."
    )
    lines.append(
        "> Every decision point stays in `shadow` until a separate reviewed diff "
        "flips it to `enforce` after the sign-off of ADR-0012, Appendix F.5."
    )
    return "\n".join(lines) + "\n"


def _certification_summary(result: DpResult) -> str:
    chosen = result.chosen
    if not chosen.certifications:
        return "no acted label has a threshold in any language"
    total = len(chosen.certifications)
    return f"{chosen.certified_scopes} of {total} scopes clear the Wilson bound"


def _findings(results: Sequence[DpResult]) -> list[str]:
    """What the reader should know before the tables: where the validation tau did
    not hold on test, and where the constraint never bound."""
    lines: list[str] = []
    for r in results:
        for c in r.chosen.certifications:
            if c.below_floor:
                lines.append(
                    f"- `{r.dp.dp_id}`, {c.scope}, `{c.label}`: {c.tp} of {c.accepted} "
                    f"decisions correct on test ({c.tp / c.accepted:.2f}) against a "
                    f"floor of {c.p_min:.2f}. The threshold chosen on validation did "
                    "not hold on the held-out split."
                )
        unbound = [
            lang
            for lang, fit in r.chosen.scalar_fits.items()
            if fit.feasible and not fit.binding
        ]
        unbound += [
            f"{lang}/{label}"
            for lang, fits in r.chosen.label_fits.items()
            for label, fit in fits.items()
            if fit.feasible and not fit.binding
        ]
        if unbound:
            lines.append(
                f"- `{r.dp.dp_id}`: the constraint rejected nothing on validation in "
                f"{', '.join(unbound)}, so those thresholds are only the lowest "
                "confidence seen (see each Thresholds table)."
            )
    if not lines:
        lines.append("- Nothing to flag: every acted label held its floor on test.")
    return lines


def _summary_rows(results: Sequence[DpResult], config: RunConfig) -> list[str]:
    rows = [
        "| Decision point | Language | Status | tau | T | Coverage val | Coverage test "
        "| Acted coverage test | ECE pre -> post (test) | Certified |",
        "|---|:---:|---|---|---:|---:|---:|---:|---|:---:|",
    ]
    for r in results:
        c = r.chosen
        for lang in config.languages:
            test, val = c.test.get(lang), c.val.get(lang)
            fit = c.calibration.get(lang)
            temperature = getattr(fit, "temperature", None)
            certs = [x for x in c.certifications if lang in x.langs]
            certified = bool(certs) and all(x.certified for x in certs)
            rows.append(
                f"| `{r.dp.dp_id}` | {lang} | {c.status if test else 'no data'} | "
                f"{_tau_text(c.thresholds.get(lang, c.thresholds.get('*')))} | "
                f"{num(temperature)} | {pct(val.coverage if val else None)} | "
                f"{pct(test.coverage if test else None)} | "
                f"{pct(test.acted_coverage if test else None)} | "
                f"{num(test.ece_pre if test else None)} -> "
                f"{num(test.ece_post if test else None)} | "
                f"{'yes' if certified else 'no'} |"
            )
    return rows


def _label_table(
    test: Mapping[str, SplitMetrics], langs: Sequence[str], acted_only: bool
) -> list[str]:
    rows = [
        "| Scope | Label | Test rows | Decided | Correct | Precision "
        "| Wilson 95% lower | Recall | Floor |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for scope in [*langs, "all"]:
        metrics = test.get(scope)
        if metrics is None:
            continue
        for label, m in metrics.labels.items():
            if acted_only and not m.acted:
                continue
            rows.append(
                f"| {scope} | `{label}` | {m.support} | {m.accepted} | {m.tp} | "
                f"{num(m.precision)} | {num(m.wilson)} | {num(m.recall)} | "
                f"{num(m.p_min, 2) if m.acted else 'not acted on'} |"
            )
    return rows


def _confusion(metrics: SplitMetrics, labels: Sequence[str]) -> list[str]:
    from calibrate.dp import ABSTAINED, OUTSIDE

    columns = [*labels, ABSTAINED]
    rows = [
        "| Truth \\ decided | " + " | ".join(f"`{c}`" for c in columns) + " |",
        "|---|" + "---:|" * len(columns),
    ]
    for truth in [*labels, OUTSIDE]:
        counts = metrics.confusion.get(truth)
        if counts is None:
            continue
        rows.append(
            f"| `{truth}` | "
            + " | ".join(str(counts.get(c, 0)) for c in columns)
            + " |"
        )
    return rows


def _reliability(result: CandidateResult, langs: Sequence[str]) -> list[str]:
    rows = [
        "| Confidence bin | "
        + " | ".join(f"{lang}: n, conf, acc" for lang in langs)
        + " |",
        "|---|" + "---|" * len(langs),
    ]
    for index in range(10):
        cells = []
        for lang in langs:
            metrics = result.test.get(lang)
            if metrics is None:
                cells.append("-")
                continue
            b = metrics.bins[index]
            cells.append(
                f"{b.n}, {b.mean_confidence:.2f}, {b.accuracy:.2f}" if b.n else "0"
            )
        low = index / 10
        rows.append(f"| {low:.1f}-{low + 0.1:.1f} | " + " | ".join(cells) + " |")
    return rows


def _dp_section(r: DpResult, config: RunConfig, embedded: str) -> str:
    c = r.chosen
    dp = r.dp
    langs = list(config.languages)
    out: list[str] = [f"## `{dp.dp_id}`", ""]
    if dp.note:
        out += [dp.note.strip(), ""]

    view = (
        ", ".join(f"`{x}`" for x in dp.labels)
        if len(dp.labels) <= 6
        else f"{len(dp.labels)} labels"
    )
    floors = ", ".join(f"`{k}` >= {v:.2f}" for k, v in dp.constraint.p_min.items())
    out += [
        f"- **View:** {view} ({dp.view.kind})",
        f"- **Acted labels and precision floor:** {floors}",
        f"- **Selection rule on validation:** `{dp.constraint.ci}` precision, at least "
        f"{dp.constraint.n_min} validation rows of a label per fitting scope",
        "- **Certification rule on test:** Wilson 95% lower bound >= floor "
        "(always, whatever the selection rule)",
        f"- **Threshold scope:** `{dp.scope}`; **calibrator:** `{dp.calibrator}`",
        f"- **Backend:** `{c.candidate.name}` (`{c.backend.spec['model_id']}`), "
        f"`{c.candidate.kind}`, {c.candidate.probability_kind}",
        "- **CPU latency (single text, host):** "
        f"p50 {c.backend.bench.p50_latency_ms:.2f} ms, "
        f"p95 {c.backend.bench.p95_latency_ms:.2f} ms (budget `timeout_ms` "
        f"{c.candidate.timeout_ms}); RAM model+inference "
        f"{c.backend.bench.peak_ram_mb:.1f} MB",
        f"- **Status written:** `{c.status}`; certified: "
        f"**{'yes' if c.certified else 'no'}** ({_certification_summary(r)})",
        "",
    ]

    out += ["### Candidate selection", "", r.rationale, ""]
    if r.others:
        out += [
            "| Candidate | Kind | Status | Certified scopes | Test acted coverage "
            "| p95 (ms) | RAM (MB) |",
            "|---|---|---|---:|---:|---:|---:|",
        ]
        for x in [c, *r.others]:
            everything = x.test.get("all")
            out.append(
                f"| `{x.candidate.name}`{' (chosen)' if x is c else ''} | "
                f"{x.candidate.kind} | {x.status} | {x.certified_scopes} | "
                f"{pct(everything.acted_coverage if everything else None)} | "
                f"{x.backend.bench.p95_latency_ms:.2f} | {x.backend.ram_mb:.1f} |"
            )
        out.append("")

    out += ["### Calibrator", ""]
    if dp.calibrator == "none":
        out += ["No calibrator: the backend's probabilities are used as they are.", ""]
    else:
        out += [
            "| Language | Validation rows | T | Log loss before -> after | Note |",
            "|:---:|---:|---:|---|---|",
        ]
        for lang in langs:
            fit = c.calibration.get(lang)
            if isinstance(fit, str) or fit is None:
                out.append(f"| {lang} | {c.n_val[lang]} | - | - | {fit or 'none'} |")
            else:
                note = (
                    "at the search bound: the fit is not identified"
                    if fit.at_bound
                    else ""
                )
                out.append(
                    f"| {lang} | {fit.n} | {fit.temperature:.4f} | "
                    f"{fit.nll_before:.3f} -> {fit.nll_after:.3f} | {note} |"
                )
        out.append("")

    out += [
        "### Thresholds",
        "",
        "| Language | tau | Fitted on | Notes |",
        "|:---:|---|---|---|",
    ]
    for lang in [*langs, *(["*"] if "*" in c.thresholds else [])]:
        entry = c.thresholds.get(lang)
        scopes = sorted({s for s in c.tau_scopes.get(lang, {}).values() if s})
        notes: list[str] = []
        fit = c.scalar_fits.get(lang)
        if fit is not None and fit.reason:
            notes.append(fit.reason)
        elif fit is not None and not fit.binding:
            notes.append(
                "not binding: every validation row is accepted, so tau is only the "
                "lowest confidence seen"
            )
        for label, label_fit in c.label_fits.get(lang, {}).items():
            if label_fit.reason:
                notes.append(f"`{label}`: {label_fit.reason}")
            elif not label_fit.binding:
                notes.append(f"`{label}`: not binding (every prediction accepted)")
        fit_scope = "pooled languages" if lang == "*" else (" and ".join(scopes) or "-")
        out.append(
            f"| {lang} | {_tau_text(entry)} | {fit_scope} | {'; '.join(notes)} |"
        )
    out.append("")

    out += [
        "### Coverage and calibration on test",
        "",
        "| Language | Validation rows | Test rows | Coverage val | Coverage test "
        "| Acted coverage test | Macro-F1 (top label) | ECE pre | ECE post "
        "| ECE <= 0.10 |",
        "|:---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for lang in [*langs, "all"]:
        test, val = c.test.get(lang), c.val.get(lang)
        if test is None:
            out.append(
                f"| {lang} | {c.n_val.get(lang, '-')} | {c.n_test.get(lang, '-')} "
                "| no data |||||||"
            )
            continue
        out.append(
            f"| {lang} | {val.n if val else '-'} | {test.n} | "
            f"{pct(val.coverage if val else None)} | {pct(test.coverage)} | "
            f"{pct(test.acted_coverage)} | {test.macro_f1:.3f} | {test.ece_pre:.3f} | "
            f"{test.ece_post:.3f} | {'yes' if test.ece_post <= ECE_TARGET else 'no'} |"
        )
    out.append("")

    out += ["### Precision on test (acted labels)", ""]
    out += _label_table(c.test, langs, acted_only=True)
    out.append("")
    if not all(
        m.acted
        for m in (c.test.get("all").labels.values() if c.test.get("all") else [])
    ):
        out += ["All labels, languages pooled:", ""]
        pooled = {"all": c.test["all"]} if "all" in c.test else {}
        out += _label_table(pooled, [], acted_only=False)
        out.append("")

    out += ["### Certification", ""]
    if not c.certifications:
        out += ["No acted label has a threshold, so there is nothing to certify.", ""]
    else:
        out += [
            "| Scope | Label | Correct / decided | Wilson 95% lower | Floor "
            "| Certified | Needs |",
            "|---|---|---:|---:|---:|:---:|---|",
        ]
        for x in c.certifications:
            needs = (
                ""
                if x.certified
                else f"{zero_error_sample_size(x.p_min)} decided with zero errors "
                f"(has {x.tp}/{x.accepted})"
            )
            out.append(
                f"| {x.scope} | `{x.label}` | {x.tp}/{x.accepted} | {num(x.wilson)} | "
                f"{x.p_min:.2f} | {'yes' if x.certified else 'no'} | {needs} |"
            )
        out.append("")

    out += [
        "### Reliability on test (after calibration; n, mean confidence, accuracy)",
        "",
    ]
    out += _reliability(c, langs)
    out.append("")

    everything = c.test.get("all")
    if everything is not None:
        out += ["### Confusion on test, languages pooled", ""]
        out += _confusion(everything, dp.labels)
        out.append("")

    out += [
        "### Hard negatives",
        "",
        "Not measured: there is no hard-negative set yet (ADR-0012, F.1 and WP9). "
        "Until there is, 'false accepts on hard negatives' is unknown, not zero.",
        "",
        "### Artifact fragment (verbatim)",
        "",
        "```json",
        embedded,
        "```",
        "",
        "### Diff against the previous artifact",
        "",
    ]
    out += [f"- `{line}`" for line in r.diff] or ["- no change"]
    out.append("")

    out += ["### Definition of done (Appendix F.5)", ""]
    ece_ok = bool(c.test) and all(
        m.ece_post <= ECE_TARGET for lang, m in c.test.items() if lang != "all"
    )
    verdict = (
        "the numeric criteria are met"
        if c.certified and ece_ok
        else "not ready for enforce"
    )
    out += [
        f"- {_mark(c.status == 'calibrated')} Artifact entry `status: calibrated` "
        f"(this run: `{c.status}`).",
        f"- {_mark(c.certified)} Constraint met on test with the Wilson bound "
        f"({_certification_summary(r)}); otherwise the shortfall belongs in "
        "`docs/limitations.md`.",
        f"- {_mark(ece_ok)} ECE after calibration <= {ECE_TARGET:.2f} on test in every "
        "language.",
        f"- {_mark(c.backend.bench.p95_latency_ms <= c.candidate.timeout_ms)} p95 "
        f"inside the DP's `timeout_ms` (RAM {c.backend.bench.peak_ram_mb:.1f} MB; "
        "the encoder's memory floor is checked by the service at startup).",
        "- [ ] `make calibration-verify` and the encoder tests pass "
        "(run after committing the artifact).",
        "- [ ] Shadow traffic or the eval run shows the DP against the LLM "
        "(`select_agreement`, `would_apply`): pending, needs WP4/WP6.",
        "- [ ] Report and artifact committed; the `enforce` diff separate and "
        "reviewed.",
        "",
        f"**Sign-off: {verdict}.** "
        "A human signs off; this harness only computes the numbers.",
        "",
    ]
    return "\n".join(out)


def render_report(
    *,
    results: Sequence[DpResult],
    config: RunConfig,
    run_id: str,
    artifact_id: str,
    artifact_target: str,
    official: bool,
    date: str,
    embedded: Mapping[str, str],
    selected: Sequence[str],
    partial: bool,
) -> str:
    lines: list[str] = ["# Decision Points Calibration Report", "", _banner(results)]
    lines += [
        f"- **Run id:** `{run_id}`",
        f"- **Date:** {date}",
        "- **Task:** `decision-points` (ADR-0012, Appendix F)",
        f"- **Decision points in this run:** {', '.join(f'`{d}`' for d in selected)}"
        + (
            " (a partial run: the other decision points of the artifact are unchanged)"
            if partial
            else ""
        ),
        f"- **Artifact:** `{artifact_target}` -> `artifact_id` `{artifact_id}` "
        + (
            "(official run: merged into the committed artifact)"
            if official
            else "(dev run: the committed artifact is untouched)"
        ),
        f"- **Environment:** {environment()}",
        "",
        "## Provenance and hashes",
        "",
        f"- **Configuration:** `{config.path}` (`{config.sha256}`)",
        "- **Data (per decision point):**",
    ]
    seen: set[tuple[str, str]] = set()
    for r in results:
        paths = r.dp.data or config.data
        for split in ("train", "validation", "test"):
            key = (getattr(paths, split), r.data_hashes[split])
            if key not in seen:
                seen.add(key)
                lines.append(f"  - `{key[0]}` ({split}): `{key[1]}`")
    lines.append(
        f"- **Test provenance:** {', '.join(sorted({r.provenance for r in results}))}"
    )
    lines.append("- **Backends:**")
    for backend_id in sorted({r.chosen.candidate.name for r in results}):
        spec = next(
            r.chosen.backend.spec
            for r in results
            if r.chosen.candidate.name == backend_id
        )
        lines.append(f"  - `{backend_id}`: `{spec['model_id']}`")
    lines += ["", "## Certification status", ""]
    lines += [
        "| Decision point | Status | Certified | Detail |",
        "|---|---|:---:|---|",
    ]
    for r in results:
        lines.append(
            f"| `{r.dp.dp_id}` | {r.chosen.status} "
            f"| {'yes' if r.chosen.certified else 'no'} | {_certification_summary(r)} |"
        )
    lines += ["", "## Findings", ""]
    lines += _findings(results)
    lines += ["", "## Summary", ""]
    lines += _summary_rows(results, config)
    lines.append("")
    for r in results:
        lines.append(_dp_section(r, config, embedded[r.dp.dp_id]))
    lines += [
        "## Residual risks",
        "",
        "- The test split is AI-written and small; per-language precision has wide "
        "intervals (see the Wilson columns). No decision point is certified.",
        "- tau was chosen with the point estimate on validation, which holds 10 rows "
        "per label and language: it is a starting point for shadow traffic, not a "
        "guarantee. Switch `constraint.ci` to `wilson95_lower` when validation is "
        "large enough to satisfy it.",
        "- Labels outside a DP's constraint (for example `other`) are decided whenever "
        "they are on top; the engine does not act on them. `out_of_scope` is a sink "
        "(short replies, bare OTP digits): where it is constrained (`smalltalk_route`) "
        "read its precision above before trusting it (ADR-0012, context item 2).",
        "- No hard-negative set exists; the gate's worst failure (a false `confirm`) "
        "is measured on ordinary utterances only.",
        "- Latency and RAM are host measurements of one process, not the container "
        "limits; `make encoder-bench` for artifact backends is pending (WP7).",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["canonical_json", "render_report"]
