"""The effects file: which decision point drives which engine effect (ADR-0012, B.4).

The effects (`record`, `select`, `gate`, `hint`, `canned_reply`) are code; this
file is the data that
binds each decision point (DP) to one of them, with a `mode`, label-to-value
maps and what to do when the DP does not decide. Validation is fail-loud, like
`SESSION_SECRET`: an invalid file stops the orchestrator from starting, and
nothing is guessed. The thresholds live in the encoder's calibration artifact,
never here.

Effects not built (`route_tools`, `propose`) are rejected with an explicit
"pending" message (AGENTS rule 7). `hint` and `canned_reply` ship in `shadow`
(ADR-0014).
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin

import yaml
from contracts import TOOL_CATALOG
from contracts.encoder import (
    DECISION_POINT_ID_PATTERN,
    MAX_DECISION_POINTS_PER_REQUEST,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from orchestrator.conversation.decisions.records import Mode

SCHEMA_VERSION = 1
DEFAULT_EFFECTS_FILE = (
    Path(__file__).resolve().parents[4] / "config" / "decision_effects.yaml"
)

IMPLEMENTED_EFFECTS = ("record", "select", "gate", "hint", "canned_reply")
PENDING_EFFECTS = ("route_tools", "propose")

# What a DP that abstains may fall back to, per effect (the first is the default).
# `record` has no fallback: it only records. Every fallback is toward the LLM's own
# argument, a withheld write, or a question; never toward acting (invariant I2).
FALLBACKS: dict[str, tuple[str, ...]] = {
    "record": (),
    "select": ("fallback_llm",),
    "gate": ("withhold",),
    # Tell the LLM the classifier was unsure, or say nothing.
    "hint": ("uncertain", "omit"),
    # Ask the canned clarification question, or leave the turn to the LLM.
    "canned_reply": ("reply", "fallback_llm"),
}
# When the DP is unavailable (encoder down, not served): narrower where it matters.
# An outage is not ambiguity, so it never produces a hint or a canned question.
UNAVAILABLE_FALLBACKS: dict[str, tuple[str, ...]] = {
    **FALLBACKS,
    "hint": ("omit",),
    "canned_reply": ("fallback_llm",),
}
# One hint and one canned reply per turn, at most.
SINGLE_USE_EFFECTS = ("hint", "canned_reply")
MAX_TEMPLATE_LENGTH = 500

# Arguments no effect may set, even when they are enums: the priority is decided
# by the policy engine, and the rest are identities and secrets.
NEVER_SELECTED = frozenset({"priority", "card_ref", "idempotency_key"})

_LABEL = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"
_LABEL_RE = re.compile(_LABEL)
MAX_AGE_TURNS_LIMIT = 50


class EffectsConfigError(ValueError):
    """The effects file (or its overrides) is invalid: the service will not start."""


# ---------------------------------------------------------------- file shape


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExplicitRequest(_Strict):
    """Consent without an extra turn: another DP decided one of these labels."""

    dp: str = Field(pattern=DECISION_POINT_ID_PATTERN)
    labels: list[str] = Field(min_length=1)


class GateParams(_Strict):
    tool: str
    consent_labels: list[str] = Field(min_length=1)
    revoke_labels: list[str] = Field(default_factory=list)
    explicit_request: ExplicitRequest | None = None
    max_age_turns: int = Field(default=6, ge=1, le=MAX_AGE_TURNS_LIMIT)


class LedgerSpec(_Strict):
    """How the labels a DP decided over the session combine into one."""

    policy: Literal["priority", "latest"]
    order: list[str] | None = Field(
        default=None, description="Strongest first; required for `priority`"
    )


class SelectTarget(_Strict):
    """One tool whose enum argument(s) the effect may overwrite.

    With `arg`, `map` is label -> value. Without it, `map` is label ->
    {arg: value, ...}.
    """

    tool: str
    arg: str | None = None
    map: dict[str, str | dict[str, str]] = Field(min_length=1)
    keep_llm_call_when: dict[str, list[str]] = Field(default_factory=dict)


class SelectParams(_Strict):
    ledger: LedgerSpec
    targets: list[SelectTarget] = Field(min_length=1)


class CannedReplyParams(_Strict):
    """The fixed clarification question, per language (ADR-0014, Appendix B)."""

    max_consecutive: int = Field(default=1, ge=1, le=3)
    templates: dict[str, str]

    @field_validator("templates")
    @classmethod
    def _every_language_asks(cls, value: dict[str, str]) -> dict[str, str]:
        from orchestrator.privacy.masking import RegexMasker

        missing = {"es", "pt", "en"} - set(value)
        if missing:
            raise ValueError(f"templates miss the language(s) {sorted(missing)}")
        unknown = set(value) - {"es", "pt", "en"}
        if unknown:
            raise ValueError(f"templates name unknown language(s) {sorted(unknown)}")
        masker = RegexMasker()
        for lang, text in value.items():
            if not text.strip() or len(text) > MAX_TEMPLATE_LENGTH:
                raise ValueError(
                    f"template {lang}: 1 to {MAX_TEMPLATE_LENGTH} characters"
                )
            if "?" not in text:
                raise ValueError(f"template {lang}: a clarification is a question")
            if not masker.verify_safe(text):
                raise ValueError(f"template {lang}: looks like it holds PII")
        return value


class RawDecisionPoint(_Strict):
    mode: Mode
    effect: str
    on_abstain: str | None = None
    on_unavailable: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("mode", mode="before")
    @classmethod
    def _yaml_reads_off_as_false(cls, value: object) -> object:
        # YAML 1.1 (PyYAML) turns an unquoted `off` into False: `mode: off` is what
        # anyone writes, so read it as what they meant.
        return Mode.OFF if value is False else value


class EffectsFile(_Strict):
    version: int
    decision_points: dict[str, RawDecisionPoint] = Field(min_length=1)

    @field_validator("version")
    @classmethod
    def _known_version(cls, value: int) -> int:
        if value != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported version {value}; this build reads {SCHEMA_VERSION}"
            )
        return value


# ---------------------------------------------------------------- bound config


@dataclass(frozen=True)
class DecisionPointConfig:
    """One validated binding of a DP to an effect."""

    id: str
    mode: Mode
    effect: str
    on_abstain: str | None
    on_unavailable: str | None
    params: GateParams | SelectParams | CannedReplyParams | None

    @property
    def active(self) -> bool:
        return self.mode is not Mode.OFF

    @property
    def enforcing(self) -> bool:
        return self.mode is Mode.ENFORCE

    def required_labels(self) -> frozenset[str]:
        """Labels the encoder's view must offer for this binding to make sense."""
        if isinstance(self.params, GateParams):
            return frozenset(self.params.consent_labels + self.params.revoke_labels)
        if isinstance(self.params, SelectParams):
            return frozenset(
                label for target in self.params.targets for label in target.map
            )
        return frozenset()


@dataclass(frozen=True)
class EffectsConfig:
    """The validated effects file, in file order."""

    decision_points: dict[str, DecisionPointConfig] = field(default_factory=dict)
    source: str = "none"

    def active(self) -> list[DecisionPointConfig]:
        return [dp for dp in self.decision_points.values() if dp.active]

    def get(self, dp_id: str) -> DecisionPointConfig | None:
        return self.decision_points.get(dp_id)

    def modes(self) -> dict[str, str]:
        return {dp.id: dp.mode.value for dp in self.decision_points.values()}


# ------------------------------------------------------------------- loading


def load_effects(
    path: str | Path | None = None,
    mode_overrides: Mapping[str, Mode] | None = None,
) -> EffectsConfig:
    """Read, validate and bind the effects file. Raises EffectsConfigError."""
    file = Path(path) if path else DEFAULT_EFFECTS_FILE
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as exc:
        raise EffectsConfigError(
            f"effects file {file} cannot be read ({type(exc).__name__}); "
            "set DECISION_EFFECTS_FILE"
        ) from exc
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise EffectsConfigError(f"effects file {file} is not valid YAML") from exc
    try:
        parsed = EffectsFile.model_validate(document)
    except ValidationError as exc:
        raise EffectsConfigError(f"effects file {file}: {_describe(exc)}") from exc
    return bind_effects(parsed, mode_overrides or {}, source=str(file))


def bind_effects(
    parsed: EffectsFile,
    mode_overrides: Mapping[str, Mode],
    source: str = "memory",
) -> EffectsConfig:
    """Validate the cross-references and apply the mode overrides."""
    unknown = sorted(set(mode_overrides) - set(parsed.decision_points))
    if unknown:
        raise EffectsConfigError(
            f"DECISION_POINTS_MODES names decision point(s) not in the effects "
            f"file: {unknown}"
        )
    if len(parsed.decision_points) > MAX_DECISION_POINTS_PER_REQUEST:
        # One analyze call names them all; over the contract ceiling it would be
        # refused whole, PII spans included.
        raise EffectsConfigError(
            f"the effects file names {len(parsed.decision_points)} decision points; "
            f"a request may name at most {MAX_DECISION_POINTS_PER_REQUEST}"
        )
    bound: dict[str, DecisionPointConfig] = {}
    for dp_id, raw in parsed.decision_points.items():
        if not re.match(DECISION_POINT_ID_PATTERN, dp_id):
            raise EffectsConfigError(f"{dp_id!r} is not a valid decision point id")
        bound[dp_id] = _bind_one(dp_id, raw, mode_overrides.get(dp_id))
    _check_references(parsed, bound)
    return EffectsConfig(decision_points=bound, source=source)


def parse_mode_overrides(raw: str | None) -> dict[str, Mode]:
    """`DECISION_POINTS_MODES='confirm_gate=shadow,block_reason=off'` -> modes.

    A typo must not silently leave a DP enforcing when someone reached for the
    kill switch, so an unreadable entry is an error, not a skip.
    """
    overrides: dict[str, Mode] = {}
    for entry in (raw or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        dp_id, separator, value = entry.partition("=")
        dp_id, value = dp_id.strip(), value.strip().lower()
        if not separator or not dp_id:
            raise EffectsConfigError(
                f"DECISION_POINTS_MODES entry {entry!r} must look like id=mode"
            )
        try:
            mode = Mode(value)
        except ValueError:
            raise EffectsConfigError(
                f"DECISION_POINTS_MODES: mode {value!r} for {dp_id!r} must be one of "
                f"{[m.value for m in Mode]}"
            ) from None
        if dp_id in overrides:
            raise EffectsConfigError(f"DECISION_POINTS_MODES names {dp_id!r} twice")
        overrides[dp_id] = mode
    return overrides


def _describe(exc: ValidationError) -> str:
    """Field paths and reasons, never the values (they could be anything)."""
    parts = []
    for error in exc.errors(include_input=False, include_url=False):
        where = ".".join(str(p) for p in error["loc"]) or "<file>"
        parts.append(f"{where}: {error['msg']}")
    return "; ".join(parts)


def _bind_one(
    dp_id: str, raw: RawDecisionPoint, override: Mode | None
) -> DecisionPointConfig:
    effect = raw.effect
    if effect in PENDING_EFFECTS:
        raise EffectsConfigError(
            f"{dp_id}: pending: {effect} is not implemented (ADR-0012)"
        )
    if effect not in IMPLEMENTED_EFFECTS:
        raise EffectsConfigError(
            f"{dp_id}: unknown effect {effect!r}; implemented: "
            f"{list(IMPLEMENTED_EFFECTS)}"
        )
    fallbacks: dict[str, str | None] = {}
    for name, value, allowed in (
        ("on_abstain", raw.on_abstain, FALLBACKS[effect]),
        ("on_unavailable", raw.on_unavailable, UNAVAILABLE_FALLBACKS[effect]),
    ):
        if value is None:
            value = allowed[0] if allowed else None
        elif value not in allowed:
            raise EffectsConfigError(
                f"{dp_id}: {name}={value!r} is not allowed for effect {effect}; "
                f"allowed: {list(allowed) or 'none'}"
            )
        fallbacks[name] = value

    params: GateParams | SelectParams | CannedReplyParams | None
    try:
        if effect in ("record", "hint"):
            if raw.params:
                raise EffectsConfigError(f"{dp_id}: effect {effect} takes no params")
            params = None
        elif effect == "canned_reply":
            params = CannedReplyParams.model_validate(raw.params)
        elif effect == "gate":
            params = _check_gate(dp_id, GateParams.model_validate(raw.params))
        else:
            params = _check_select(dp_id, SelectParams.model_validate(raw.params))
    except ValidationError as exc:
        raise EffectsConfigError(f"{dp_id}: params: {_describe(exc)}") from exc

    return DecisionPointConfig(
        id=dp_id,
        mode=override or raw.mode,
        effect=effect,
        on_abstain=fallbacks["on_abstain"],
        on_unavailable=fallbacks["on_unavailable"],
        params=params,
    )


def _check_labels(dp_id: str, labels: list[str], what: str) -> None:
    for label in labels:
        if not _LABEL_RE.match(label):
            raise EffectsConfigError(f"{dp_id}: {what} {label!r} is not a valid label")
    if len(set(labels)) != len(labels):
        raise EffectsConfigError(f"{dp_id}: {what} repeats a label")


def _check_gate(dp_id: str, params: GateParams) -> GateParams:
    definition = TOOL_CATALOG.get(params.tool)
    if definition is None:
        raise EffectsConfigError(
            f"{dp_id}: gate tool {params.tool!r} is not a known tool"
        )
    if not definition.mutates_state:
        raise EffectsConfigError(
            f"{dp_id}: gate tool {params.tool!r} does not write; a gate holds writes"
        )
    _check_labels(dp_id, params.consent_labels, "consent_labels")
    _check_labels(dp_id, params.revoke_labels, "revoke_labels")
    if set(params.consent_labels) & set(params.revoke_labels):
        raise EffectsConfigError(
            f"{dp_id}: a label cannot both grant and revoke consent"
        )
    if params.explicit_request is not None:
        _check_labels(dp_id, params.explicit_request.labels, "explicit_request.labels")
    return params


def _check_select(dp_id: str, params: SelectParams) -> SelectParams:
    ledger = params.ledger
    if ledger.policy == "priority":
        if not ledger.order:
            raise EffectsConfigError(f"{dp_id}: ledger policy priority needs an order")
        _check_labels(dp_id, ledger.order, "ledger.order")
    elif ledger.order is not None:
        raise EffectsConfigError(f"{dp_id}: ledger policy latest takes no order")

    seen: set[tuple[str, str]] = set()
    for target in params.targets:
        definition = TOOL_CATALOG.get(target.tool)
        if definition is None:
            raise EffectsConfigError(
                f"{dp_id}: select tool {target.tool!r} is not a known tool"
            )
        _check_labels(dp_id, list(target.map), "map label")
        if ledger.policy == "priority" and set(target.map) != set(ledger.order or ()):
            raise EffectsConfigError(
                f"{dp_id}: the labels mapped for {target.tool} must be exactly the "
                "ledger order"
            )
        assignments = _assignments(dp_id, target)
        for arg in _args_of(assignments):
            _check_enum_arg(dp_id, target.tool, arg)
            if (target.tool, arg) in seen:
                raise EffectsConfigError(
                    f"{dp_id}: {target.tool}.{arg} is selected twice"
                )
            seen.add((target.tool, arg))
        for label, values in assignments.items():
            for arg, value in values.items():
                if value not in enum_values(target.tool, arg):
                    raise EffectsConfigError(
                        f"{dp_id}: {target.tool}.{arg} has no value {value!r} "
                        f"(mapped from {label})"
                    )
        for arg, values in target.keep_llm_call_when.items():
            _check_enum_arg(dp_id, target.tool, arg, selecting=False)
            for value in values:
                if value not in enum_values(target.tool, arg):
                    raise EffectsConfigError(
                        f"{dp_id}: keep_llm_call_when {target.tool}.{arg} has no "
                        f"value {value!r}"
                    )
    return params


def _assignments(dp_id: str, target: SelectTarget) -> dict[str, dict[str, str]]:
    """label -> {arg: value}, whichever of the two shapes the target uses."""
    out: dict[str, dict[str, str]] = {}
    for label, value in target.map.items():
        if target.arg is not None:
            if not isinstance(value, str):
                raise EffectsConfigError(
                    f"{dp_id}: {target.tool}.{target.arg}: map values must be strings"
                )
            out[label] = {target.arg: value}
        else:
            if not isinstance(value, dict) or not value:
                raise EffectsConfigError(
                    f"{dp_id}: {target.tool}: without `arg`, each map value must be "
                    "{arg: value}"
                )
            out[label] = dict(value)
    if len({frozenset(values) for values in out.values()}) > 1:
        raise EffectsConfigError(
            f"{dp_id}: {target.tool}: every label must set the same arguments"
        )
    return out


def _args_of(assignments: dict[str, dict[str, str]]) -> list[str]:
    first = next(iter(assignments.values()))
    return list(first)


def _check_enum_arg(dp_id: str, tool: str, arg: str, selecting: bool = True) -> None:
    """The argument exists on the tool and is an enum the effect may touch."""
    if selecting and arg in NEVER_SELECTED:
        raise EffectsConfigError(f"{dp_id}: {tool}.{arg} can never be selected")
    if not enum_values(tool, arg):
        raise EffectsConfigError(f"{dp_id}: {tool}.{arg} is not an enum argument")


def enum_values(tool: str, arg: str) -> frozenset[str]:
    """Members of the enum behind `tool.arg`; empty if it is not an enum."""
    field_info = TOOL_CATALOG[tool].input_model.model_fields.get(arg)
    if field_info is None:
        return frozenset()
    annotation: Any = field_info.annotation
    candidates = (
        get_args(annotation)
        if get_origin(annotation) in (Union, UnionType)
        else (annotation,)
    )
    for candidate in candidates:
        if isinstance(candidate, type) and issubclass(candidate, Enum):
            return frozenset(str(member.value) for member in candidate)
    return frozenset()


def _check_references(
    parsed: EffectsFile, bound: dict[str, DecisionPointConfig]
) -> None:
    """A DP another block refers to exists in the file and is not `off` there.

    The check reads the file's own modes: a `DECISION_POINTS_MODES=turn_intent=off`
    override is the kill switch and must stay usable, so it starts and simply
    leaves the explicit request unable to grant anything.
    """
    gates: dict[str, str] = {}
    selected: dict[tuple[str, str], str] = {}
    single: dict[str, str] = {}
    for dp in bound.values():
        if dp.effect in SINGLE_USE_EFFECTS:
            owner = single.setdefault(dp.effect, dp.id)
            if owner != dp.id:
                raise EffectsConfigError(
                    f"{dp.id}: only one decision point may use {dp.effect} "
                    f"({owner} already does)"
                )
        if isinstance(dp.params, SelectParams):
            for target in dp.params.targets:
                for arg in _args_of(_assignments(dp.id, target)):
                    owner = selected.setdefault((target.tool, arg), dp.id)
                    if owner != dp.id:
                        raise EffectsConfigError(
                            f"{dp.id}: {target.tool}.{arg} is already selected by "
                            f"{owner}"
                        )
        if not isinstance(dp.params, GateParams):
            continue
        if dp.params.tool in gates:
            raise EffectsConfigError(
                f"{dp.id}: {dp.params.tool} is already gated by {gates[dp.params.tool]}"
            )
        gates[dp.params.tool] = dp.id
        request = dp.params.explicit_request
        if request is None:
            continue
        referenced = parsed.decision_points.get(request.dp)
        if referenced is None:
            raise EffectsConfigError(
                f"{dp.id}: explicit_request names {request.dp!r}, which is not in "
                "the effects file"
            )
        if referenced.mode is Mode.OFF:
            raise EffectsConfigError(
                f"{dp.id}: explicit_request names {request.dp!r}, which is off"
            )
