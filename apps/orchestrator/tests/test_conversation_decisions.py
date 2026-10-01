"""Decision points inside the turn engine (ADR-0012): fake LLM, respx for the rest.

The gate and the select are exercised through `TurnEngine.run_turn`, against the
shipped effects file with modes overridden the way an operator would. What these
tests pin down: `shadow` changes nothing the LLM or banking-core sees; `enforce`
holds a `card.block` until the customer consents, without a banking-core call or
an idempotency ordinal, and never in the open direction; a decision point can
never cost the PII spans; and nothing run-varying reaches the LLM.
"""

import json
from typing import Any

import httpx
import pytest
import respx
from contracts import ReasonCode, ReceiptBlock, ToolResultStatus
from orchestrator.chat.engine_handler import EngineTurnHandler
from orchestrator.config import Settings
from orchestrator.conversation import TurnEngine
from orchestrator.conversation.decisions.config import EffectsConfigError, load_effects
from orchestrator.conversation.decisions.effects import DecisionRuntime
from orchestrator.conversation.decisions.records import Mode
from orchestrator.conversation.decisions.state import (
    ConsentSource,
    DecisionState,
    GateState,
    GateStatus,
)
from orchestrator.conversation.prompt import PROMPT_VERSION, SYSTEM_PROMPT
from orchestrator.encoder_client import EncoderClient
from orchestrator.session.models import ConversationState
from orchestrator.tools_client import BankingCoreClient

from .fake_encoder import (
    ABSTAIN,
    ENCODER_URL,
    LEGACY_SEED,
    FakeEncoder,
)
from .fake_llm import ScriptedLLM, Step, tool_call
from .test_conversation_engine import (
    BANKING_URL,
    SESSION_ID,
    FakeBankingCore,
    assert_no_dangling_tool_calls,
    new_context,
)
from .test_conversation_required_handoff import (
    REQUIRED,
    TRANSACTION_ID,
    block_data,
    handoff_blocks,
)

BLOCK_ARGS = {"card_ref": "card_ab12cd34", "reason": "LOST"}
ASK = "¿Confirmas que quieres que bloquee tu tarjeta?"
DONE = "Listo: bloqueé tu tarjeta."


def name_spans(text: str) -> list[dict[str, Any]]:
    """The encoder's PII span for the name "Ana", if the text has it."""
    start = text.find("Ana")
    if start < 0:
        return []
    return [{"type": "NAME", "start": start, "end": start + 3}]


def block_step(call_id: str = "call_1", **args: Any) -> Step:
    return Step(tool_calls=[tool_call(call_id, "card_block", {**BLOCK_ARGS, **args})])


@pytest.fixture
def services() -> Any:
    with respx.mock(assert_all_called=False) as router:
        yield router


class Rig:
    """Engine, fake encoder and fake banking-core wired together."""

    def __init__(
        self,
        services: Any,
        llm: ScriptedLLM,
        modes: dict[str, str] | None = None,
        script: list[dict[str, str]] | None = None,
        banking: FakeBankingCore | None = None,
        empty_runtime: bool = False,
        collect_eval: bool = False,
        **encoder: Any,
    ) -> None:
        self.llm = llm
        self.encoder = FakeEncoder(services, script=script, **encoder)
        self.banking = banking or FakeBankingCore()
        services.post(f"{BANKING_URL}/v1/tools/call").mock(side_effect=self.banking)
        settings = Settings()
        self.runtime = (
            DecisionRuntime.empty()
            if empty_runtime
            else DecisionRuntime(
                load_effects(
                    mode_overrides={k: Mode(v) for k, v in (modes or {}).items()}
                )
            )
        )
        self.engine = TurnEngine(
            llm=llm,
            banking=BankingCoreClient(base_url=BANKING_URL, settings=settings),
            encoder=EncoderClient(base_url=ENCODER_URL, timeout=1.0, settings=settings),
            decisions=self.runtime,
            collect_eval=collect_eval,
        )
        self.context = new_context()

    async def say(self, text: str, turn_id: str) -> Any:
        return await self.engine.run_turn(self.context, text, turn_id=turn_id)

    def blocks(self) -> list[dict[str, Any]]:
        return self.banking.calls_to("card.block")


def tool_contents(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [json.loads(m["content"]) for m in history if m["role"] == "tool"]


# ----------------------------------------------------------------- shadow mode


async def test_shadow_changes_nothing_the_llm_or_banking_core_sees() -> None:
    def steps() -> ScriptedLLM:
        return ScriptedLLM([block_step(), Step(content=DONE)])

    script = [{"turn_intent": "report_lost_card", "block_reason": "STOLEN"}]
    with respx.mock(assert_all_called=False) as router:
        with_dp = Rig(router, steps(), script=script)  # every DP ships in shadow
        result = await with_dp.say("Perdí mi tarjeta, bloquéala", "t1")
    with respx.mock(assert_all_called=False) as router:
        without = Rig(router, steps(), script=script, empty_runtime=True)
        baseline = await without.say("Perdí mi tarjeta, bloquéala", "t1")

    assert with_dp.llm.calls == without.llm.calls  # same messages, same tools
    assert with_dp.banking.requests == without.banking.requests
    assert [b.model_dump() for b in result.blocks] == [
        b.model_dump() for b in baseline.blocks
    ]
    assert with_dp.context.history == without.context.history
    # ... while the metadata says what enforce would have done
    [withheld] = [e for e in result.metadata.effects if e.effect == "gate"]
    assert (withheld.would_apply, withheld.applied) == (True, False)
    [select] = [e for e in result.metadata.effects if e.effect == "select"]
    assert select.detail["dp_value"] == "STOLEN" and not select.applied
    assert baseline.metadata.decisions == [] and baseline.metadata.effects == []


async def test_the_shipped_configuration_is_all_shadow_and_the_first_card_block_goes(
    services: Any,
) -> None:
    rig = Rig(
        services,
        ScriptedLLM([block_step(), Step(content=DONE)]),
        script=[{"turn_intent": "report_lost_card"}],
    )

    result = await rig.say("Perdí mi tarjeta", "t1")

    assert {d.mode for d in result.metadata.decisions} == {Mode.SHADOW}
    assert len(rig.blocks()) == 1
    assert any(isinstance(b, ReceiptBlock) for b in result.blocks)


# ------------------------------------------------------------ the gate, enforce


async def test_a_withheld_card_block_never_reaches_banking_core(services: Any) -> None:
    rig = Rig(
        services,
        ScriptedLLM([block_step(), Step(content=ASK)]),
        modes={"confirm_gate": "enforce"},
        script=[{"turn_intent": "report_lost_card", "confirm_gate": "other"}],
    )

    result = await rig.say("Perdí mi tarjeta", "t1")

    assert rig.banking.requests == []
    [outcome] = result.metadata.tool_outcomes
    assert outcome.tool == "card.block"
    assert outcome.status is ToolResultStatus.REFUSED
    assert outcome.reason_code is ReasonCode.CONFIRMATION_REQUIRED
    assert outcome.executed is False
    [feedback] = tool_contents(rig.context.history)
    assert feedback == {
        "tool": "card.block",
        "status": "refused",
        "reason_code": "CONFIRMATION_REQUIRED",
        "data": None,
    }
    assert_no_dangling_tool_calls(rig.context.history)
    assert [b.text for b in result.blocks] == [ASK]  # type: ignore[union-attr]
    gate = rig.context.decisions.gates["card.block"]
    assert gate.status is GateStatus.PENDING


async def test_the_customers_yes_releases_the_block_with_the_first_ordinal(
    services: Any,
) -> None:
    llm = ScriptedLLM(
        [
            block_step("c1"),
            Step(content=ASK),
            block_step("c2"),
            Step(content=DONE),
        ]
    )
    rig = Rig(
        services,
        llm,
        modes={"confirm_gate": "enforce"},
        script=[
            {"turn_intent": "report_lost_card", "confirm_gate": "other"},
            {"turn_intent": "confirm", "confirm_gate": "confirm"},
        ],
    )
    await rig.say("Perdí mi tarjeta", "t1")

    second = await rig.say("sí, bloquéala", "t2")

    [sent] = rig.blocks()
    # The withheld call of turn 1 took no ordinal, and turn 2 is a turn of its own.
    assert sent["idempotency_key"] == TurnEngine._idempotency_key(
        SESSION_ID, "t2", "card.block", 0
    )
    assert any(isinstance(b, ReceiptBlock) for b in second.blocks)
    assert rig.context.decisions.gates == {}
    granted = [
        e for e in second.metadata.effects if e.detail.get("event") == "consent_granted"
    ]
    assert granted[0].detail["consent_source"] == ConsentSource.CONFIRMATION.value
    assert (granted[0].applied, granted[0].would_apply) == (True, True)


async def test_the_key_of_the_released_block_is_what_an_ungated_turn_would_use() -> (
    None
):
    with respx.mock(assert_all_called=False) as router:
        ungated = Rig(
            router,
            ScriptedLLM([block_step(), Step(content=DONE)]),
            modes={"confirm_gate": "off"},
        )
        await ungated.say("Bloquea mi tarjeta", "t9")
    with respx.mock(assert_all_called=False) as router:
        gated = Rig(
            router,
            ScriptedLLM([block_step(), Step(content=DONE)]),
            modes={"confirm_gate": "enforce"},
            script=[{"turn_intent": "request_card_block"}],
        )
        await gated.say("Bloquea mi tarjeta", "t9")

    assert (
        gated.blocks()[0]["idempotency_key"] == ungated.blocks()[0]["idempotency_key"]
    )


async def test_an_explicit_request_needs_no_extra_turn(services: Any) -> None:
    rig = Rig(
        services,
        ScriptedLLM([block_step(), Step(content=DONE)]),
        modes={"confirm_gate": "enforce"},
        script=[{"turn_intent": "request_card_block", "confirm_gate": "other"}],
    )

    result = await rig.say("Bloquea mi tarjeta ya", "t1")

    assert len(rig.blocks()) == 1
    assert any(isinstance(b, ReceiptBlock) for b in result.blocks)


async def test_a_deny_closes_the_gate_and_a_later_proposal_is_withheld_again(
    services: Any,
) -> None:
    rig = Rig(
        services,
        ScriptedLLM(
            [
                block_step("c1"),
                Step(content=ASK),
                Step(content="Entendido, no la bloqueo."),
                block_step("c3"),
                Step(content=ASK),
            ]
        ),
        modes={"confirm_gate": "enforce"},
        script=[
            {"turn_intent": "report_lost_card"},
            {"turn_intent": "deny", "confirm_gate": "deny"},
            {"turn_intent": "report_lost_card", "confirm_gate": "other"},
        ],
    )

    await rig.say("Perdí mi tarjeta", "t1")
    await rig.say("no, déjalo", "t2")
    assert rig.context.decisions.gates == {}
    await rig.say("bueno, perdí la tarjeta igual", "t3")

    assert rig.banking.requests == []


async def test_an_abstained_answer_keeps_the_question_open(services: Any) -> None:
    rig = Rig(
        services,
        ScriptedLLM(
            [block_step("c1"), Step(content=ASK), block_step("c2"), Step(content=ASK)]
        ),
        modes={"confirm_gate": "enforce"},
        script=[
            {"turn_intent": "report_lost_card"},
            {"turn_intent": ABSTAIN, "confirm_gate": ABSTAIN},
        ],
    )

    await rig.say("Perdí mi tarjeta", "t1")
    second = await rig.say("mmm... sipi", "t2")

    assert rig.banking.requests == []
    assert (
        second.metadata.tool_outcomes[0].reason_code is ReasonCode.CONFIRMATION_REQUIRED
    )
    assert rig.context.decisions.gates["card.block"].status is GateStatus.PENDING


async def test_the_model_cannot_retry_a_withheld_call_within_the_turn(
    services: Any,
) -> None:
    rig = Rig(
        services,
        ScriptedLLM([block_step("c1"), block_step("c2"), Step(content=ASK)]),
        modes={"confirm_gate": "enforce"},
        script=[{"turn_intent": "report_lost_card"}],
    )

    result = await rig.say("Perdí mi tarjeta", "t1")

    assert rig.banking.requests == []
    assert [o.reason_code for o in result.metadata.tool_outcomes] == [
        ReasonCode.CONFIRMATION_REQUIRED,
        ReasonCode.CONFIRMATION_REQUIRED,
    ]
    # One withheld decision, not two: the second was the relayed refusal.
    assert len([e for e in result.metadata.effects if e.effect == "gate"]) == 1


async def test_consent_that_went_stale_does_not_release_the_block(
    services: Any,
) -> None:
    rig = Rig(
        services,
        ScriptedLLM([block_step(), Step(content=ASK)]),
        modes={"confirm_gate": "enforce"},
        script=[{"turn_intent": "report_lost_card"}],
    )
    rig.context.decisions = DecisionState(
        turn=20,
        gates={
            "card.block": GateState(
                status=GateStatus.CONSENTED,
                since_turn=10,
                source=ConsentSource.CONFIRMATION,
            )
        },
    )

    result = await rig.say("Perdí mi tarjeta", "t1")

    assert rig.banking.requests == []
    assert result.metadata.effects[0].detail["event"] == "consent_expired"


async def test_a_yes_to_something_else_grants_nothing(services: Any) -> None:
    rig = Rig(
        services,
        ScriptedLLM([block_step(), Step(content=ASK)]),
        modes={"confirm_gate": "enforce"},
        script=[{"turn_intent": "confirm", "confirm_gate": "confirm"}],
    )

    await rig.say("sí", "t1")  # nothing is pending yet

    assert rig.banking.requests == []


async def test_the_gate_holds_the_write_when_the_encoder_is_down(
    services: Any, caplog: pytest.LogCaptureFixture
) -> None:
    llm = ScriptedLLM([block_step(), Step(content=ASK)])
    rig = Rig(services, llm, modes={"confirm_gate": "enforce"})
    services.post(f"{ENCODER_URL}/v1/analyze").mock(
        side_effect=httpx.ConnectError("down")
    )

    result = await rig.say("Perdí mi tarjeta, soy ana@bank.com", "t1")

    assert result.metadata.encoder_unavailable is True
    assert result.metadata.masking_regex_only is True
    assert {
        (d.outcome.value, d.unavailable_reason) for d in result.metadata.decisions
    } == {("unavailable", "encoder_unavailable")}
    assert rig.banking.requests == []
    assert "ana@bank.com" not in llm.payload_dump()  # masking still works
    assert [b.text for b in result.blocks] == [ASK]  # type: ignore[union-attr]


# ---------------------------------------------- the gate and the required handoff


async def test_a_withheld_block_creates_no_handoff_and_the_released_one_creates_one(
    services: Any,
) -> None:
    banking = FakeBankingCore(data=block_data(REQUIRED))
    args = {"transaction_id": TRANSACTION_ID, "reason": "UNRECOGNIZED_CHARGE"}
    rig = Rig(
        services,
        ScriptedLLM(
            [
                block_step("c1", **args),
                Step(content=ASK),
                block_step("c2", **args),
                Step(content="Bloqueé y un agente revisará el caso."),
            ]
        ),
        modes={"confirm_gate": "enforce"},
        script=[
            {"turn_intent": "report_unrecognized_charge"},
            {"turn_intent": "confirm", "confirm_gate": "confirm"},
        ],
        banking=banking,
    )

    first = await rig.say("Hay un cargo que no reconozco", "t1")
    assert banking.requests == []
    assert handoff_blocks(first) == []

    second = await rig.say("sí", "t2")

    assert [r["body"]["tool"] for r in banking.requests] == [
        "card.block",
        "handoff.create",
    ]
    assert len(handoff_blocks(second)) == 1
    [handoff_call] = banking.calls_to("handoff.create")
    assert handoff_call["args"]["priority"] == "URGENT"
    assert_no_dangling_tool_calls(rig.context.history)


async def test_the_gate_does_not_touch_a_handoff_the_model_creates(
    services: Any,
) -> None:
    rig = Rig(
        services,
        ScriptedLLM(
            [
                Step(
                    tool_calls=[
                        tool_call(
                            "c1",
                            "handoff_create",
                            {"reason": "CUSTOMER_REQUEST", "summary": "Wants a person"},
                        )
                    ]
                ),
                Step(content="Te paso con un agente."),
            ]
        ),
        modes={"confirm_gate": "enforce"},
        script=[{"turn_intent": "request_human_agent"}],
    )

    result = await rig.say("Quiero hablar con una persona", "t1")

    assert len(rig.banking.calls_to("handoff.create")) == 1
    assert len(handoff_blocks(result)) == 1


# ----------------------------------------------------------------- select


async def test_enforce_sends_the_decided_reason_and_history_keeps_the_llms(
    services: Any,
) -> None:
    rig = Rig(
        services,
        ScriptedLLM([block_step(reason="LOST"), Step(content=DONE)]),
        modes={"confirm_gate": "off", "block_reason": "enforce"},
        script=[{"turn_intent": "report_stolen_card", "block_reason": "STOLEN"}],
    )

    result = await rig.say("Me robaron la tarjeta", "t1")

    [sent] = rig.blocks()
    assert sent["args"]["reason"] == "STOLEN"
    recorded = next(m for m in rig.context.history if m.get("tool_calls"))
    arguments = json.loads(recorded["tool_calls"][0]["function"]["arguments"])
    assert arguments["reason"] == "LOST"  # what the model emitted, so replay keys hold
    [select] = [e for e in result.metadata.effects if e.effect == "select"]
    assert select.applied and select.detail["llm_value"] == "LOST"


async def test_enforce_routes_a_handoff_but_never_changes_its_priority(
    services: Any,
) -> None:
    rig = Rig(
        services,
        ScriptedLLM(
            [
                Step(
                    tool_calls=[
                        tool_call(
                            "c1",
                            "handoff_create",
                            {
                                "reason": "CUSTOMER_REQUEST",
                                "summary": "Wants to dispute a charge",
                                "priority": "LOW",
                                "department": "CUSTOMER_SUPPORT",
                            },
                        )
                    ]
                ),
                Step(content="Un agente de disputas te contactará."),
            ]
        ),
        modes={"confirm_gate": "off", "handoff_route": "enforce"},
        script=[{"turn_intent": "request_dispute", "handoff_route": "DISPUTE"}],
    )

    await rig.say("Quiero disputar un cargo", "t1")

    [sent] = rig.banking.calls_to("handoff.create")
    assert sent["args"]["department"] == "DISPUTES"
    assert sent["args"]["reason"] == "DISPUTE_CLAIM"
    assert sent["args"]["priority"] == "LOW"


async def test_the_handoff_the_engine_creates_for_a_required_block_is_not_routed(
    services: Any,
) -> None:
    rig = Rig(
        services,
        ScriptedLLM([block_step(transaction_id=TRANSACTION_ID), Step(content=DONE)]),
        modes={
            "confirm_gate": "off",
            "block_reason": "off",
            "handoff_route": "enforce",
        },
        script=[
            {"turn_intent": "request_human_agent", "handoff_route": "HUMAN_REQUEST"}
        ],
        banking=FakeBankingCore(data=block_data(REQUIRED)),
    )

    await rig.say("Bloquea y pásame con alguien", "t1")

    [sent] = rig.banking.calls_to("handoff.create")
    assert sent["args"]["department"] == "DISPUTES"  # banking-core's requirement
    assert sent["args"]["reason"] == "UNRECOGNIZED_TRANSACTION"


# ------------------------------------------- what is requested from the encoder


async def test_in_legacy_seed_mode_only_turn_intent_is_ever_requested(
    services: Any,
) -> None:
    rig = Rig(
        services,
        ScriptedLLM([Step(content="Hola."), Step(content="Hola de nuevo.")]),
        served=LEGACY_SEED,
        script=[{"turn_intent": "greeting"}],
    )

    first = await rig.say("hola", "t1")
    await rig.say("hola otra vez", "t2")

    assert [r["decision_points"] for r in rig.encoder.requests] == [
        ["turn_intent"],
        ["turn_intent"],
    ]
    assert rig.encoder.listings == 1  # cached
    by_id = {d.dp_id: d for d in first.metadata.decisions}
    assert by_id["turn_intent"].outcome.value == "decided"
    assert by_id["confirm_gate"].unavailable_reason == "not_served"


async def test_a_listing_that_cannot_be_read_names_nothing_and_costs_nothing(
    services: Any,
) -> None:
    llm = ScriptedLLM([Step(content="Hola.")])
    rig = Rig(services, llm, listing_down=True, pii=name_spans)

    result = await rig.say("Hola, soy Ana", "t1")

    assert "decision_points" not in rig.encoder.requests[0]
    assert "Ana" not in llm.payload_dump()  # the encoder's PII span still masked it
    assert result.metadata.encoder_unavailable is False


async def test_a_stale_listing_is_asked_again_without_losing_the_pii_spans(
    services: Any,
) -> None:
    llm = ScriptedLLM(
        [Step(content="Hola."), Step(content="Otra vez."), Step(content="Hola.")]
    )
    rig = Rig(services, llm, pii=name_spans)
    await rig.say("Hola, soy otra persona", "t1")
    assert rig.encoder.listings == 1
    rig.encoder.served = LEGACY_SEED  # the encoder restarted without an artifact

    second = await rig.say("Hola, soy Ana", "t2")

    # the cached listing still named confirm_gate: 422, then the default request
    assert rig.encoder.requests[-2]["decision_points"][1] == "confirm_gate"
    assert "decision_points" not in rig.encoder.requests[-1]
    assert "Ana" not in llm.payload_dump()
    assert second.metadata.encoder_unavailable is False
    assert rig.encoder.listings == 1  # invalidated, fetched again on the next turn

    await rig.say("hola de nuevo", "t3")

    assert rig.encoder.listings == 2
    assert rig.encoder.requests[-1]["decision_points"] == ["turn_intent"]


async def test_no_decision_point_is_requested_when_none_is_configured(
    services: Any,
) -> None:
    rig = Rig(
        services,
        ScriptedLLM([Step(content="Hola.")]),
        empty_runtime=True,
    )

    await rig.say("hola", "t1")

    assert rig.encoder.requests == [{"text": "hola", "lang": "es"}]
    assert rig.encoder.listings == 0


# ---------------------------------------------------------- state and metadata


async def test_the_decision_state_is_committed_only_when_the_turn_completes(
    services: Any,
) -> None:
    rig = Rig(
        services,
        ScriptedLLM([block_step()]),  # the model runs out of steps mid-turn
        modes={"confirm_gate": "enforce"},
        script=[{"turn_intent": "report_lost_card"}],
    )

    with pytest.raises(AssertionError):
        await rig.say("Perdí mi tarjeta", "t1")

    assert rig.context.decisions == DecisionState()
    assert rig.context.history == []


async def test_a_retried_turn_runs_again_from_the_same_state(services: Any) -> None:
    def make() -> ScriptedLLM:
        return ScriptedLLM([block_step(), Step(content=ASK)])

    rig = Rig(
        services,
        make(),
        modes={"confirm_gate": "enforce"},
        script=[{"turn_intent": "report_lost_card"}],
    )
    rig.engine.llm = ScriptedLLM([])  # the first attempt dies
    with pytest.raises(AssertionError):
        await rig.say("Perdí mi tarjeta", "t1")

    rig.engine.llm = make()
    result = await rig.say("Perdí mi tarjeta", "t1")

    assert (
        result.metadata.tool_outcomes[0].reason_code is ReasonCode.CONFIRMATION_REQUIRED
    )
    assert rig.context.decisions.turn == 1


async def test_nothing_a_decision_produced_reaches_the_llm(services: Any) -> None:
    llm = ScriptedLLM([block_step(), Step(content=ASK)])
    rig = Rig(
        services,
        llm,
        modes={"confirm_gate": "enforce", "block_reason": "enforce"},
        script=[{"turn_intent": "report_lost_card", "block_reason": "STOLEN"}],
    )

    await rig.say("Perdí mi tarjeta", "t1")

    payload = llm.payload_dump()
    for run_varying in (
        "0.97",
        "0.9",
        "confidence",
        "cfg0123456789",
        "tfidf_lr",
        "tau",
    ):
        assert run_varying not in payload
    # the only trace is the categorical refusal
    assert "CONFIRMATION_REQUIRED" in payload
    assert "confirm_gate" not in payload and "block_reason" not in payload


async def test_the_state_travels_with_the_conversation(services: Any) -> None:
    rig = Rig(
        services,
        ScriptedLLM([block_step(), Step(content=ASK)]),
        modes={"confirm_gate": "enforce"},
        script=[{"turn_intent": "report_lost_card"}],
    )
    handler = EngineTurnHandler(rig.engine)
    conversation = ConversationState(banking_session_id=SESSION_ID, language="es")

    outcome = await handler.handle_turn(conversation, "Perdí mi tarjeta", turn_id="t1")

    assert conversation.decisions.turn == 1
    assert conversation.decisions.gates["card.block"].status is GateStatus.PENDING
    assert outcome.metadata["decisions"][0]["dp_id"] == "turn_intent"
    revived = ConversationState.model_validate_json(conversation.model_dump_json())
    assert revived.decisions == conversation.decisions


def test_a_conversation_stored_before_decision_points_still_loads() -> None:
    stored = ConversationState(banking_session_id=SESSION_ID).model_dump(mode="json")
    del stored["decisions"]

    revived = ConversationState.model_validate(stored)

    assert revived.decisions == DecisionState()


async def test_the_eval_hook_carries_the_decision_records(services: Any) -> None:
    rig = Rig(
        services,
        ScriptedLLM([block_step(), Step(content=DONE)]),
        script=[{"turn_intent": "report_lost_card", "block_reason": "STOLEN"}],
        collect_eval=True,
    )

    result = await rig.say("Perdí mi tarjeta", "t1")

    assert result.eval.decisions == result.metadata.decisions
    assert result.eval.effects == result.metadata.effects
    assert {d.dp_id for d in result.eval.decisions} >= {"turn_intent", "confirm_gate"}
    assert "Perdí" not in result.eval.model_dump_json(exclude={"masked_outbound"})


# ----------------------------------------------------------------- the prompt


def test_the_prompt_explains_the_refusal_and_holds_no_policy() -> None:
    assert PROMPT_VERSION == "turn-engine/2"
    assert "CONFIRMATION_REQUIRED" in SYSTEM_PROMPT
    assert "one short question" in SYSTEM_PROMPT
    # explanatory only: the gate is code, and no threshold or mode is in the text
    for word in ("threshold", "shadow", "enforce", "confirm_gate", "tau"):
        assert word not in SYSTEM_PROMPT.lower()


@pytest.mark.parametrize(
    "settings",
    [
        {"DECISION_EFFECTS_FILE": "/nonexistent/effects.yaml"},
        {"DECISION_POINTS_MODES": "confirm_gate=on"},
        {"DECISION_POINTS_MODES": "no_such_dp=off"},
    ],
    ids=["missing-file", "bad-mode", "unknown-decision-point"],
)
def test_the_service_refuses_to_start_on_a_bad_configuration(
    settings: dict[str, str],
) -> None:
    with pytest.raises(EffectsConfigError):
        TurnEngine.from_settings(Settings(_env_file=None, **settings))


# ------------------------------------------------------------ market (ADR-0014)


async def test_the_market_reaches_the_encoder_only_while_it_matches_the_language(
    services: Any,
) -> None:
    rig = Rig(services, ScriptedLLM([Step(content=DONE)] * 3))
    await rig.say("hola", "t1")  # no market: the legacy body
    rig.context.locale = "es-MX"
    result = await rig.say("me robaron la tarjeta", "t2")
    assert result.metadata.locale == "es-MX"
    rig.context.locale = "pt-BR"  # contradicts the conversation's Spanish
    stale = await rig.say("perdí mi tarjeta", "t3")
    assert stale.metadata.locale is None
    sent = [body.get("locale") for body in rig.encoder.requests]
    assert sent == [None, "es-MX", None]
    assert "locale" not in rig.encoder.requests[0]
