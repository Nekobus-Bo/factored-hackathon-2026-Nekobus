"""The decision-point section of the report, over fake evidence (ADR-0012).

The evidence is what the orchestrator's eval hook would send: decision records
and the effects that acted (or, in shadow, would have) on the turn's calls. The
section counts them per language; it never turns them into a pass or a fail.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from evalrunner.decisions import proportion, summarize, wilson_interval
from evalrunner.models import (
    DecisionEvidence,
    EffectEvidence,
    ScenarioRunResult,
    TurnResult,
)
from evalrunner.report import render_evaluation_report


def dp(
    dp_id: str,
    outcome: str,
    label: str | None = None,
    effect: str = "record",
    mode: str = "shadow",
    reason: str | None = None,
    config: str | None = "cfg0123456789",
) -> DecisionEvidence:
    return DecisionEvidence(
        dp_id=dp_id,
        effect=effect,
        mode=mode,
        outcome=outcome,
        label=label,
        confidence=0.9 if outcome == "decided" else 0.0,
        config_version=config,
        unavailable_reason=reason,
    )


def gate(
    event: str,
    mode: str = "shadow",
    would: bool = True,
    applied: bool = False,
    source: str | None = None,
) -> EffectEvidence:
    return EffectEvidence(
        dp_id="confirm_gate",
        effect="gate",
        mode=mode,
        tool="card.block",
        applied=applied,
        would_apply=would,
        detail={"event": event, "consent_source": source},
    )


def select(
    arg: str,
    llm: str | None,
    value: str | None,
    mode: str = "shadow",
    applied: bool = False,
) -> EffectEvidence:
    return EffectEvidence(
        dp_id="block_reason",
        effect="select",
        mode=mode,
        tool="card.block",
        applied=applied,
        would_apply=value is not None and value != llm,
        detail={"arg": arg, "llm_value": llm, "dp_value": value},
    )


def scenario(
    lang: str, *turns: TurnResult, scenario_id: str = "s"
) -> ScenarioRunResult:
    return ScenarioRunResult(
        scenario_id=f"{scenario_id}_{lang}",
        lang=lang,
        group="happy_path",
        passed=True,
        turns=list(turns),
    )


def turn(
    decisions: list[DecisionEvidence] | None = None,
    effects: list[EffectEvidence] | None = None,
    unreadable: int = 0,
) -> TurnResult:
    return TurnResult(
        decisions=decisions or [],
        effects=effects or [],
        decisions_unreadable=unreadable,
    )


# ---------------------------------------------------------------------- Wilson


def test_wilson_matches_the_figures_the_adr_quotes() -> None:
    low, _ = wilson_interval(22, 22) or (0.0, 0.0)
    assert low == pytest.approx(
        0.851, abs=0.001
    )  # "22/22 has a Wilson lower bound of 0.85"
    low, high = wilson_interval(8, 14) or (0.0, 0.0)
    assert (round(low, 3), round(high, 3)) == (0.326, 0.786)


def test_wilson_of_nothing_is_nothing() -> None:
    assert wilson_interval(0, 0) is None
    assert proportion(0, 0) == "n/a"


def test_a_proportion_shows_the_counts_and_the_interval() -> None:
    assert proportion(8, 14) == "57.1% (8/14) [32.6, 78.6]"


# --------------------------------------------------------------------- counting


def test_decision_points_are_counted_per_language_and_outcome() -> None:
    results = [
        scenario(
            "es",
            turn(
                [
                    dp("turn_intent", "decided", "report_lost_card"),
                    dp("confirm_gate", "abstained", effect="gate"),
                ]
            ),
            turn(
                [
                    dp("turn_intent", "abstained"),
                    dp("confirm_gate", "decided", "confirm", effect="gate"),
                ]
            ),
        ),
        scenario(
            "pt",
            turn(
                [
                    dp(
                        "turn_intent",
                        "unavailable",
                        reason="encoder_unavailable",
                        config=None,
                    ),
                    dp("confirm_gate", "infeasible", effect="gate"),
                ]
            ),
        ),
    ]

    summary = summarize(results)

    es = summary["es"].dps
    assert (es["turn_intent"].turns, es["turn_intent"].decided) == (2, 1)
    assert es["turn_intent"].abstained == 1
    assert es["turn_intent"].labels == {"report_lost_card": 1}
    assert (es["confirm_gate"].decided, es["confirm_gate"].abstained) == (1, 1)
    pt = summary["pt"].dps
    assert pt["turn_intent"].unavailable == 1
    assert pt["turn_intent"].reasons == {"encoder_unavailable": 1}
    assert pt["confirm_gate"].other == 1  # infeasible
    assert not summary["en"].has_evidence
    assert (summary["es"].scenarios, summary["es"].turns) == (1, 2)


def test_the_gate_counts_what_it_would_have_withheld_apart_from_what_it_did() -> None:
    results = [
        scenario(
            "es",
            turn(effects=[gate("withheld")]),  # shadow: would withhold
            turn(
                effects=[
                    gate("consent_granted", source="confirmation"),
                    gate("released", would=False),
                ]
            ),
            scenario_id="a",
        ),
        scenario(
            "es",
            turn(effects=[gate("released", would=False)]),
            scenario_id="b",
        ),
        scenario(
            "es",
            turn(
                effects=[
                    gate("withheld", mode="enforce", applied=True),
                    gate("consent_revoked"),
                    gate("consent_expired"),
                ]
            ),
            scenario_id="c",
        ),
    ]

    counts = summarize(results)["es"].gates["confirm_gate"]

    assert counts.tool == "card.block"
    assert counts.modes == {"shadow", "enforce"}
    assert counts.proposals == 4  # 2 withheld + 2 released
    assert counts.would_withhold == 1
    assert counts.withheld == 1
    assert counts.released == 2
    assert counts.consent == {"confirmation": 1}
    assert (counts.revoked, counts.expired) == (1, 1)
    assert counts.scenarios_with_withhold == 2  # a and c, not b


def test_selects_count_agreement_overrides_and_missing_decisions() -> None:
    results = [
        scenario(
            "es",
            turn(effects=[select("reason", "LOST", "LOST")]),  # agrees
            turn(effects=[select("reason", "LOST", "STOLEN")]),  # would override
            turn(
                effects=[
                    select("reason", "LOST", "STOLEN", mode="enforce", applied=True)
                ]
            ),
            turn(effects=[select("reason", "LOST", None)]),  # nothing decided
        )
    ]

    counts = summarize(results)["es"].selects[("block_reason", "reason")]

    assert counts.evaluated == 4
    assert counts.no_decision == 1
    assert counts.agree == 1
    assert counts.would_override == 2
    assert counts.applied == 1


def test_records_that_could_not_be_read_are_counted() -> None:
    results = [
        scenario("en", turn([dp("turn_intent", "decided", "greeting")], unreadable=2))
    ]

    assert summarize(results)["en"].unreadable == 2


def test_languages_outside_the_report_are_ignored() -> None:
    results = [scenario("fr", turn([dp("turn_intent", "decided", "greeting")]))]

    assert not any(s.has_evidence for s in summarize(results).values())


# ----------------------------------------------------------------------- report


def render(results: list[ScenarioRunResult], tmp_path: Path) -> str:
    out = render_evaluation_report("fake", results, tmp_path / "eval.md")
    return out.read_text(encoding="utf-8")


def section_of(text: str) -> str:
    start = text.index("## 4. Decision Points by Language (ADR-0012)")
    end = text.find("\n## ", start + 1)
    return text[start:] if end < 0 else text[start:end]


def test_the_report_has_a_per_language_decision_point_section(tmp_path: Path) -> None:
    results = [
        scenario(
            "es",
            turn(
                [
                    dp("turn_intent", "decided", "report_lost_card"),
                    dp("confirm_gate", "abstained", effect="gate"),
                    dp("block_reason", "decided", "STOLEN", effect="select"),
                ],
                [gate("withheld"), select("reason", "LOST", "STOLEN")],
            ),
            turn(
                [
                    dp(
                        "turn_intent",
                        "unavailable",
                        reason="encoder_unavailable",
                        config=None,
                    )
                ]
            ),
        ),
        scenario("pt", turn([dp("turn_intent", "decided", "greeting")])),
    ]

    section = section_of(render(results, tmp_path))

    assert "### es" in section and "### pt" in section and "### en" in section
    en = section[section.index("### en") :]
    assert en.strip().endswith("no data")
    es = section[section.index("### es") : section.index("### pt")]
    assert "| `turn_intent` | record | shadow | 2 | 1 | 0 | 1 | 0 | 50.0% (1/2)" in es
    assert "| `confirm_gate` | gate | shadow | 1 | 0 | 1 | 0 | 0 | 0.0% (0/1)" in es
    assert "Unavailable because: `turn_intent`: encoder_unavailable ×1." in es
    assert "Gate `confirm_gate` on `card.block` (shadow):" in es
    assert "| 1 | 1 | 0 | 0 | none | 0 | 0 | 1/1 |" in es
    assert "| `block_reason` | `card.block.reason` | shadow | 1 | 0 | 0.0% (0/1)" in es
    assert "- **Calibration artifact (`config_version`):** `cfg0123456789`" in section


def test_a_run_without_decision_evidence_says_so_and_infers_nothing(
    tmp_path: Path,
) -> None:
    text = render([scenario("es", turn())], tmp_path)

    section = section_of(text)
    assert "No decision-point evidence" in section
    assert "Nothing is inferred" in section
    assert "### es" not in section


def test_unreadable_records_are_flagged_in_the_report(tmp_path: Path) -> None:
    results = [
        scenario("es", turn([dp("turn_intent", "decided", "greeting")], unreadable=3))
    ]

    assert "**3 decision record(s) could not be read**" in section_of(
        render(results, tmp_path)
    )


def test_the_section_never_contains_a_pass_or_fail_of_a_decision(
    tmp_path: Path,
) -> None:
    results = [scenario("es", turn([dp("turn_intent", "decided", "greeting")]))]

    section = section_of(render(results, tmp_path)).lower()

    for word in ("pass", "fail", "violation", "precision:"):
        assert word not in section


def test_the_report_of_a_system_without_the_field_is_unchanged_above_the_section(
    tmp_path: Path,
) -> None:
    text = render([scenario("es", turn())], tmp_path)

    assert text.index("## 3. Scenario Results Detail") < text.index(
        "## 4. Decision Points"
    )


@pytest.mark.parametrize("field", ["decisions", "effects"])
def test_evidence_models_ignore_fields_they_do_not_know(field: str) -> None:
    payload: dict[str, Any] = {
        "dp_id": "turn_intent",
        "effect": "record",
        "outcome": "decided",
        "future_field": 1,
    }
    if field == "effects":
        payload |= {"effect": "gate"}
        assert EffectEvidence.model_validate(payload).dp_id == "turn_intent"
    else:
        assert DecisionEvidence.model_validate(payload).outcome == "decided"
