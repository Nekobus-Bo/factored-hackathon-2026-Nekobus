"""Test-only encoder: scripted decisions behind the two endpoints the engine uses.

Lives in tests/ so src/ can never import it. It behaves like the real service in
the two ways the engine relies on: it evaluates only the decision points a
request names (all listed ones when none are named), and it answers 422 to an id
it does not know, which fails the whole call.
"""

import json
from collections.abc import Callable
from typing import Any

import httpx
from contracts import AnalyzeResponse, DecisionOutcome, DecisionResult, TauSource

ENCODER_URL = "http://encoder.test"
CONFIG_VERSION = "cfg0123456789"
MODEL_ID = "tfidf_lr@train-sha256:a563c0c445d6"

ABSTAIN = "<abstain>"
UNAVAILABLE = "<unavailable>"
INFEASIBLE = "<infeasible>"
OFF = "<off>"

INTENTS = [
    "report_lost_card",
    "report_stolen_card",
    "report_unrecognized_charge",
    "report_suspicious_activity",
    "request_card_block",
    "request_dispute",
    "request_human_agent",
    "confirm",
    "deny",
    "greeting",
    "out_of_scope",
]

# What the artifact serves: id -> labels of its view.
FULL_VIEWS: dict[str, list[str]] = {
    "turn_intent": INTENTS,
    "confirm_gate": ["confirm", "deny", "other"],
    "block_reason": [
        "LOST",
        "STOLEN",
        "UNRECOGNIZED_CHARGE",
        "SUSPICIOUS_ACTIVITY",
        "CUSTOMER_REQUEST",
    ],
    "handoff_route": ["DISPUTE", "FRAUD", "UNRECOGNIZED", "HUMAN_REQUEST"],
    "smalltalk_route": ["greeting", "out_of_scope", "other"],
}


def decision(dp_id: str, label: str) -> DecisionResult:
    """A DecisionResult for a label, or for one of the special outcomes."""
    common: dict[str, Any] = {
        "dp_id": dp_id,
        "model_id": MODEL_ID,
        "config_version": CONFIG_VERSION,
        "latency_ms": 0.4,
    }
    if label == ABSTAIN:
        return DecisionResult(
            outcome=DecisionOutcome.ABSTAINED,
            confidence=0.31,
            raw_confidence=0.2,
            tau=0.9,
            tau_source=TauSource.ARTIFACT,
            **common,
        )
    special = {
        UNAVAILABLE: DecisionOutcome.UNAVAILABLE,
        INFEASIBLE: DecisionOutcome.INFEASIBLE,
        OFF: DecisionOutcome.OFF,
    }
    if label in special:
        return DecisionResult(outcome=special[label], confidence=0.0, **common)
    return DecisionResult(
        outcome=DecisionOutcome.DECIDED,
        label=label,
        confidence=0.97,
        raw_confidence=0.6,
        tau=0.9,
        tau_source=TauSource.ARTIFACT,
        **common,
    )


def analysis(
    decisions: dict[str, str] | None = None,
    pii_spans: list[dict[str, Any]] | None = None,
    config_version: str | None = CONFIG_VERSION,
) -> AnalyzeResponse:
    """An AnalyzeResponse whose legacy fields follow `turn_intent`, as the real one."""
    results = {dp: decision(dp, label) for dp, label in (decisions or {}).items()}
    intent = "report_lost_card"
    abstain = False
    turn_intent = results.get("turn_intent")
    if turn_intent is not None:
        if turn_intent.label is not None:
            intent = turn_intent.label
        elif turn_intent.outcome is DecisionOutcome.ABSTAINED:
            abstain = True
    return AnalyzeResponse.model_validate(
        {
            "intent": None if abstain else intent,
            "confidence": 0.5 if abstain else 0.93,
            "abstain": abstain,
            "slots": [],
            "pii_spans": pii_spans or [],
            "model_id": MODEL_ID,
            "latency_ms": 1.0,
            "decisions": {k: v.model_dump(mode="json") for k, v in results.items()},
            "config_version": config_version,
        }
    )


def listing(
    views: dict[str, list[str]] | None = None,
    source: str = "artifact",
) -> dict[str, Any]:
    """The body of GET /v1/decision-points."""
    views = FULL_VIEWS if views is None else views
    return {
        "config_version": CONFIG_VERSION if source == "artifact" else None,
        "source": source,
        "decision_points": [
            {
                "id": dp_id,
                "labels": labels,
                "backend_kind": "tfidf_lr",
                "backend_model_id": MODEL_ID,
                "probability_kind": "distribution",
                "status": "calibrated" if source == "artifact" else "uncalibrated_seed",
                "state": "ready",
                "enabled": True,
                "always_on": True,
                "languages_with_tau": ["es", "pt", "en"],
            }
            for dp_id, labels in views.items()
        ],
    }


LEGACY_SEED = listing({"turn_intent": INTENTS}, source="legacy_seed")


class FakeEncoder:
    """Wires `/v1/analyze` and `/v1/decision-points` onto a respx router.

    `script` is consumed one entry per analyze call (the last one repeats); an
    entry maps dp id -> label (or ABSTAIN, UNAVAILABLE, ...). `requests` keeps
    every analyze body, `listings` counts the GETs of the listing.
    """

    def __init__(
        self,
        router: Any,
        served: dict[str, Any] | None = None,
        script: list[dict[str, str]] | None = None,
        pii: Callable[[str], list[dict[str, Any]]] | None = None,
        listing_down: bool = False,
    ) -> None:
        self.served = listing() if served is None else served
        self.script = script or [{}]
        self.pii = pii
        self.listing_down = listing_down
        self.requests: list[dict[str, Any]] = []
        self.listings = 0
        self.turn = 0
        router.get(f"{ENCODER_URL}/v1/decision-points").mock(side_effect=self._list)
        router.post(f"{ENCODER_URL}/v1/analyze").mock(side_effect=self._analyze)

    def _list(self, request: httpx.Request) -> httpx.Response:
        self.listings += 1
        if self.listing_down:
            return httpx.Response(503, json={"detail": "uncalibrated"})
        return httpx.Response(200, json=self.served)

    def _analyze(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        known = {dp["id"] for dp in self.served["decision_points"]}
        named = body.get("decision_points")
        unknown = sorted(set(named or []) - known)
        if unknown:
            return httpx.Response(
                422, json={"detail": f"unknown decision points {unknown}"}
            )
        wanted = self.script[min(self.turn, len(self.script) - 1)]
        self.turn += 1
        evaluated = sorted(known) if named is None else named
        spans = self.pii(body["text"]) if self.pii else []
        result = analysis(
            {dp: label for dp, label in wanted.items() if dp in evaluated},
            pii_spans=spans,
            config_version=self.served["config_version"],
        )
        return httpx.Response(200, json=result.model_dump(mode="json"))
