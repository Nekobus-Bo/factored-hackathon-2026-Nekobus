"""The effects file is validated at startup and fails loud (ADR-0012, B.4).

The shipped file must load with every decision point in `shadow` except `intent_hint`
and `clarify_route` (ADR-0014, amendment 2026-10-01); anything the
loader cannot prove safe (an argument that is not an enum, a value the tool does
not accept, `priority`, an effect the freeze does not build) stops the service.
"""

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from orchestrator.conversation.decisions.config import (
    DEFAULT_EFFECTS_FILE,
    EffectsConfigError,
    load_effects,
    parse_mode_overrides,
)
from orchestrator.conversation.decisions.records import Mode

SHIPPED: dict[str, Any] = yaml.safe_load(DEFAULT_EFFECTS_FILE.read_text("utf-8"))


def write(tmp_path: Path, document: Any) -> Path:
    path = tmp_path / "effects.yaml"
    path.write_text(
        document
        if isinstance(document, str)
        else yaml.safe_dump(document, sort_keys=False),
        encoding="utf-8",
    )
    return path


def mutated(change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    document = copy.deepcopy(SHIPPED)
    change(document)
    return document


# ------------------------------------------------------------ the shipped file


def test_the_shipped_file_loads_with_the_shipped_modes() -> None:
    config = load_effects()

    assert list(config.decision_points) == [
        "turn_intent",
        "confirm_gate",
        "block_reason",
        "handoff_route",
        "smalltalk_route",
        "intent_hint",
        "clarify_route",
    ]
    assert config.modes() == {
        "turn_intent": "shadow",
        "confirm_gate": "shadow",
        "block_reason": "shadow",
        "handoff_route": "shadow",
        "smalltalk_route": "shadow",
        "intent_hint": "enforce",
        "clarify_route": "enforce",
    }
    assert {dp.id: dp.effect for dp in config.decision_points.values()} == {
        "turn_intent": "record",
        "confirm_gate": "gate",
        "block_reason": "select",
        "handoff_route": "select",
        "smalltalk_route": "record",
        "intent_hint": "hint",
        "clarify_route": "canned_reply",
    }


def test_the_gate_fails_toward_a_withheld_write_and_selects_toward_the_llm() -> None:
    config = load_effects()

    gate = config.decision_points["confirm_gate"]
    assert (gate.on_abstain, gate.on_unavailable) == ("withhold", "withhold")
    for dp_id in ("block_reason", "handoff_route"):
        select = config.decision_points[dp_id]
        assert (select.on_abstain, select.on_unavailable) == (
            "fallback_llm",
            "fallback_llm",
        )


def test_the_labels_the_encoder_must_serve_follow_from_the_bindings() -> None:
    config = load_effects()

    assert config.decision_points["turn_intent"].required_labels() == frozenset()
    assert config.decision_points["confirm_gate"].required_labels() == {
        "confirm",
        "deny",
    }
    assert config.decision_points["handoff_route"].required_labels() == {
        "DISPUTE",
        "FRAUD",
        "UNRECOGNIZED",
        "HUMAN_REQUEST",
    }


def test_a_missing_file_stops_startup(tmp_path: Path) -> None:
    with pytest.raises(EffectsConfigError, match="cannot be read"):
        load_effects(tmp_path / "nope.yaml")


def test_a_file_that_is_not_yaml_stops_startup(tmp_path: Path) -> None:
    with pytest.raises(EffectsConfigError, match="not valid YAML"):
        load_effects(write(tmp_path, "decision_points: [unclosed"))


# --------------------------------------------------------------- mode overrides


def test_mode_overrides_are_parsed() -> None:
    assert parse_mode_overrides(" confirm_gate=shadow , block_reason=OFF,") == {
        "confirm_gate": Mode.SHADOW,
        "block_reason": Mode.OFF,
    }
    assert parse_mode_overrides("") == {}
    assert parse_mode_overrides(None) == {}


@pytest.mark.parametrize(
    "raw, message",
    [
        ("confirm_gate", "id=mode"),
        ("=shadow", "id=mode"),
        ("confirm_gate=maybe", "must be one of"),
        ("confirm_gate=shadow,confirm_gate=off", "twice"),
    ],
)
def test_an_unreadable_override_is_an_error_not_a_skip(raw: str, message: str) -> None:
    with pytest.raises(EffectsConfigError, match=message):
        parse_mode_overrides(raw)


def test_an_override_replaces_the_mode_of_the_file() -> None:
    config = load_effects(
        mode_overrides={"confirm_gate": Mode.ENFORCE, "block_reason": Mode.OFF}
    )

    assert config.decision_points["confirm_gate"].mode is Mode.ENFORCE
    assert config.decision_points["block_reason"].mode is Mode.OFF
    assert config.decision_points["turn_intent"].mode is Mode.SHADOW
    assert "block_reason" not in [dp.id for dp in config.active()]


def test_the_kill_switch_can_turn_the_gate_down_from_enforce(tmp_path: Path) -> None:
    document = mutated(
        lambda d: d["decision_points"]["confirm_gate"].update(mode="enforce")
    )

    config = load_effects(write(tmp_path, document), {"confirm_gate": Mode.SHADOW})

    assert config.decision_points["confirm_gate"].mode is Mode.SHADOW


def test_an_override_for_an_unknown_decision_point_is_an_error() -> None:
    with pytest.raises(EffectsConfigError, match="not in the effects file"):
        load_effects(mode_overrides={"confirm_gat": Mode.OFF})


def test_turning_off_the_decision_point_a_gate_reads_still_starts() -> None:
    # The kill switch must stay usable: the explicit request just grants nothing.
    config = load_effects(mode_overrides={"turn_intent": Mode.OFF})

    assert config.decision_points["turn_intent"].mode is Mode.OFF
    assert config.decision_points["confirm_gate"].mode is Mode.SHADOW


# ------------------------------------------------------------ what is rejected


@pytest.mark.parametrize("effect", ["route_tools", "propose"])
def test_effects_the_freeze_does_not_build_are_rejected_as_pending(
    tmp_path: Path, effect: str
) -> None:
    document = mutated(
        lambda d: d["decision_points"]["smalltalk_route"].update(effect=effect)
    )

    with pytest.raises(
        EffectsConfigError,
        match=f"pending: {effect} is not implemented \\(ADR-0012\\)",
    ):
        load_effects(write(tmp_path, document))


def test_an_unknown_effect_is_rejected(tmp_path: Path) -> None:
    document = mutated(
        lambda d: d["decision_points"]["turn_intent"].update(effect="teleport")
    )

    with pytest.raises(EffectsConfigError, match="unknown effect 'teleport'"):
        load_effects(write(tmp_path, document))


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda d: d.update(version=2), "unsupported version"),
        (lambda d: d.update(surprise=1), "surprise"),
        (lambda d: d.update(decision_points={}), "decision_points"),
        (
            lambda d: d["decision_points"]["turn_intent"].update(mode="maybe"),
            "turn_intent.mode",
        ),
        (
            lambda d: d["decision_points"]["turn_intent"].update(tau=0.5),
            "turn_intent.tau",
        ),
        (
            lambda d: d["decision_points"]["turn_intent"].update(on_abstain="withhold"),
            "on_abstain='withhold' is not allowed for effect record",
        ),
        (
            lambda d: d["decision_points"]["turn_intent"].update(params={"x": 1}),
            "record takes no params",
        ),
        (
            lambda d: d["decision_points"]["confirm_gate"].update(
                on_abstain="fallback_llm"
            ),
            "on_abstain='fallback_llm' is not allowed for effect gate",
        ),
        (
            lambda d: d["decision_points"]["block_reason"].update(
                on_unavailable="withhold"
            ),
            "on_unavailable='withhold' is not allowed for effect select",
        ),
    ],
    ids=[
        "version",
        "unknown-top-level-key",
        "no-decision-points",
        "unknown-mode",
        "threshold-in-the-file",
        "record-with-fallback",
        "record-with-params",
        "gate-falls-to-the-llm",
        "select-withholds",
    ],
)
def test_a_malformed_file_stops_startup(
    tmp_path: Path, change: Callable[[dict[str, Any]], None], message: str
) -> None:
    with pytest.raises(EffectsConfigError, match=message):
        load_effects(write(tmp_path, mutated(change)))


def gate_params(document: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = document["decision_points"]["confirm_gate"]["params"]
    return params


def select_target(document: dict[str, Any], dp_id: str) -> dict[str, Any]:
    target: dict[str, Any] = document["decision_points"][dp_id]["params"]["targets"][0]
    return target


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda d: gate_params(d).update(tool="card.list"), "does not write"),
        (lambda d: gate_params(d).update(tool="card.freeze"), "not a known tool"),
        (lambda d: gate_params(d).update(consent_labels=[]), "consent_labels"),
        (
            lambda d: gate_params(d).update(revoke_labels=["confirm"]),
            "grant and revoke",
        ),
        (lambda d: gate_params(d).update(max_age_turns=0), "max_age_turns"),
        (lambda d: gate_params(d).update(max_age_turns=500), "max_age_turns"),
        (lambda d: gate_params(d).update(surprise=1), "surprise"),
        (
            lambda d: gate_params(d).update(
                explicit_request={"dp": "no_such", "labels": ["x"]}
            ),
            "which is not in the effects file",
        ),
        (
            lambda d: d["decision_points"]["turn_intent"].update(mode="off"),
            "which is off",
        ),
        (
            lambda d: d["decision_points"].update(
                second_gate=copy.deepcopy(d["decision_points"]["confirm_gate"])
            ),
            "already gated by confirm_gate",
        ),
    ],
    ids=[
        "tool-that-does-not-write",
        "unknown-tool",
        "no-consent-label",
        "label-grants-and-revokes",
        "zero-age",
        "huge-age",
        "unknown-param",
        "explicit-request-of-nothing",
        "explicit-request-of-an-off-dp",
        "two-gates-on-one-tool",
    ],
)
def test_a_gate_that_cannot_be_trusted_stops_startup(
    tmp_path: Path, change: Callable[[dict[str, Any]], None], message: str
) -> None:
    with pytest.raises(EffectsConfigError, match=message):
        load_effects(write(tmp_path, mutated(change)))


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda d: select_target(d, "block_reason").update(arg="card_ref"), "card_ref"),
        (
            lambda d: select_target(d, "block_reason").update(arg="transaction_id"),
            "not an enum",
        ),
        (lambda d: select_target(d, "block_reason").update(arg="nope"), "not an enum"),
        (
            lambda d: select_target(d, "block_reason").update(tool="otp.verify"),
            "not an enum",
        ),
        (
            lambda d: select_target(d, "block_reason").update(tool="card.freeze"),
            "not a known tool",
        ),
        (
            lambda d: select_target(d, "block_reason")["map"].update(LOST="BROKEN"),
            "has no value 'BROKEN'",
        ),
        (
            lambda d: select_target(d, "block_reason")["map"].update(LOST={"a": "b"}),
            "map values must be strings",
        ),
        (
            lambda d: select_target(d, "block_reason")["map"].pop("LOST"),
            "exactly the ledger order",
        ),
        (
            lambda d: d["decision_points"]["block_reason"]["params"]["ledger"].pop(
                "order"
            ),
            "needs an order",
        ),
        (
            lambda d: d["decision_points"]["handoff_route"]["params"]["ledger"].update(
                order=["DISPUTE"]
            ),
            "takes no order",
        ),
        (
            lambda d: select_target(d, "handoff_route")["map"]["DISPUTE"].update(
                priority="URGENT"
            ),
            "same arguments",
        ),
        (
            lambda d: select_target(d, "handoff_route")["map"].update(
                {
                    k: {"priority": "URGENT"}
                    for k in list(select_target(d, "handoff_route")["map"])
                }
            ),
            "can never be selected",
        ),
        (
            lambda d: select_target(d, "handoff_route")["map"]["FRAUD"].update(
                reason="NOT_A_REASON"
            ),
            "has no value 'NOT_A_REASON'",
        ),
        (
            lambda d: select_target(d, "handoff_route").update(
                keep_llm_call_when={"reason": ["NOT_A_REASON"]}
            ),
            "keep_llm_call_when",
        ),
        (
            lambda d: select_target(d, "handoff_route").update(
                keep_llm_call_when={"summary": ["x"]}
            ),
            "not an enum",
        ),
        (
            lambda d: d["decision_points"].update(
                second=copy.deepcopy(d["decision_points"]["block_reason"])
            ),
            "already selected by block_reason",
        ),
    ],
    ids=[
        "card-ref",
        "free-text-arg",
        "unknown-arg",
        "tool-without-that-enum",
        "unknown-tool",
        "value-not-in-the-enum",
        "dict-where-a-string-belongs",
        "ledger-label-without-a-value",
        "priority-ledger-without-order",
        "latest-ledger-with-order",
        "labels-set-different-args",
        "priority-is-never-selected",
        "reason-not-in-the-enum",
        "keep-value-not-in-the-enum",
        "keep-arg-not-an-enum",
        "two-dps-select-one-arg",
    ],
)
def test_a_select_that_could_set_something_unsafe_stops_startup(
    tmp_path: Path, change: Callable[[dict[str, Any]], None], message: str
) -> None:
    with pytest.raises(EffectsConfigError, match=message):
        load_effects(write(tmp_path, mutated(change)))


def test_an_unquoted_off_in_the_yaml_means_off(tmp_path: Path) -> None:
    # PyYAML reads a bare `off` as the boolean False; the file is written by hand.
    text = DEFAULT_EFFECTS_FILE.read_text("utf-8").replace(
        "  smalltalk_route:\n    mode: shadow", "  smalltalk_route:\n    mode: off"
    )
    assert "mode: off" in text

    config = load_effects(write(tmp_path, text))

    assert config.decision_points["smalltalk_route"].mode is Mode.OFF


def test_an_unquoted_on_is_not_a_mode(tmp_path: Path) -> None:
    text = DEFAULT_EFFECTS_FILE.read_text("utf-8").replace(
        "  smalltalk_route:\n    mode: shadow", "  smalltalk_route:\n    mode: on"
    )

    with pytest.raises(EffectsConfigError, match="smalltalk_route.mode"):
        load_effects(write(tmp_path, text))


# ------------------------------------------------ hint and canned_reply (ADR-0014)


def _clarify(d: dict[str, Any]) -> dict[str, Any]:
    return d["decision_points"]["clarify_route"]


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda d: _clarify(d).update(on_unavailable="reply"), "on_unavailable"),
        (
            lambda d: d["decision_points"]["intent_hint"].update(
                on_unavailable="uncertain"
            ),
            "on_unavailable",
        ),
        (lambda d: _clarify(d)["params"]["templates"].pop("pt"), "miss the language"),
        (
            lambda d: _clarify(d)["params"]["templates"].update(en="Tell me more."),
            "is a question",
        ),
        (
            lambda d: _clarify(d)["params"]["templates"].update(
                es="¿Tu correo es ana@example.com?"
            ),
            "holds PII",
        ),
        (
            lambda d: _clarify(d)["params"]["templates"].update(es="¿" + "a" * 600),
            "characters",
        ),
        (lambda d: _clarify(d)["params"].update(max_consecutive=5), "max_consecutive"),
        (
            lambda d: d["decision_points"]["intent_hint"].update(params={"x": 1}),
            "takes no params",
        ),
        (
            lambda d: d["decision_points"]["smalltalk_route"].update(effect="hint"),
            "only one decision point may use hint",
        ),
    ],
)
def test_hint_and_canned_reply_are_validated_at_load(
    tmp_path: Path, change: Callable[[dict[str, Any]], None], message: str
) -> None:
    with pytest.raises(EffectsConfigError, match=message):
        load_effects(write(tmp_path, mutated(change)))


def test_the_shipped_clarification_is_a_question_in_every_language() -> None:
    params = load_effects().decision_points["clarify_route"].params
    assert params is not None
    templates = params.templates  # type: ignore[union-attr]
    assert set(templates) == {"es", "pt", "en"}
    assert all("?" in text for text in templates.values())
