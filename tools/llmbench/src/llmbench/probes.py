"""Skill probes: one decision of the model, in a state the oracle walked it to.

A probe is a short conversation. The oracle plays the prefix turns through the
real engine and sandbox; the model under test then gets one customer turn, and
the probe scores what it did there:

- `decision`: the allowed first decisions, a catalog tool name or null (a text
  reply with no tool call);
- `require`: tools the model must propose during the turn, with matching
  arguments on the first proposal of each;
- `forbid`: tools the model must not propose at all in the turn (proposed, not
  executed: banking-core refusing a bad call does not make the call good);
- `max_proposals`: a ceiling per tool (a retry after a refusal is a second one);
- `reply`: the language matches, it asks a question, it claims no block that no
  receipt backs (evalrunner's U5 check, over the whole conversation's receipts);
- `no_leak`: values the customer typed that must reach neither the provider (the
  masked outbound messages) nor the reply, such as a PIN or a CVV.

A prefix turn may name calls the oracle expects banking-core to refuse
(`expect_refused`), to build a history with a refusal in it.

An argument matcher is a literal, a list (any of), `re:<pattern>`, or an oracle
template (`{{card}}`, `{{tx:<merchant>}}`) resolved against the sandbox.
"""

import json
import re
from pathlib import Path
from typing import Any

import yaml
from contracts.tools.card_list import CardStatus
from evalrunner.checks import check_u5_claim_without_receipt
from orchestrator.conversation.tools import build_llm_tools
from pydantic import BaseModel, ConfigDict, Field

from llmbench.episodes import turn_result
from llmbench.harness import Conversation, TurnRecord
from llmbench.oracle import OracleLLM, OracleTurn, Resolver
from llmbench.provider import BenchProvider
from llmbench.sandbox import BankSetup, ExtraCard, SandboxBank
from llmbench.scoring import asks_question, detect_lang, lang_matches

PROBES_DIR = Path("tools/llmbench/probes")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OracleCall(_Model):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class PrefixTurn(_Model):
    user: str
    calls: list[OracleCall] = Field(default_factory=list)
    reply: str = ""
    expect_refused: list[str] = Field(default_factory=list)


class ReplyExpect(_Model):
    lang: bool = True
    question: bool = False
    no_block_claim: bool = True


class Expect(_Model):
    decision: list[str | None]
    require: dict[str, dict[str, Any]] = Field(default_factory=dict)
    forbid: list[str] = Field(default_factory=list)
    max_proposals: dict[str, int] = Field(default_factory=dict)
    reply: ReplyExpect = Field(default_factory=ReplyExpect)
    no_leak: list[str] = Field(default_factory=list)


class ProbeTurn(_Model):
    user: str
    expect: Expect


class SetupSpec(_Model):
    customer: str | None = None
    card_status: CardStatus | None = None
    otp_channel_present: bool = True
    thresholds_minor: dict[str, int] | None = None
    amount_mode: str = "flag"
    enabled_tools: list[str] = Field(default_factory=list)
    failing_tools: list[str] = Field(default_factory=list)
    extra_cards: list[dict[str, Any]] = Field(default_factory=list)

    def bank_setup(self) -> BankSetup:
        return BankSetup(
            customer=self.customer,
            card_status=self.card_status,
            otp_channel_present=self.otp_channel_present,
            thresholds_minor=self.thresholds_minor,
            amount_mode="block" if self.amount_mode == "block" else "flag",
            enabled_tools=frozenset(self.enabled_tools),
            failing_tools=frozenset(self.failing_tools),
            extra_cards=[ExtraCard(**card) for card in self.extra_cards],
        )


class Probe(_Model):
    id: str
    lang: str
    skill: str
    description: str
    setup: SetupSpec = Field(default_factory=SetupSpec)
    prefix: list[PrefixTurn] = Field(default_factory=list)
    probe: ProbeTurn


class CheckResult(_Model):
    name: str
    passed: bool
    detail: str = ""


class ProbeResult(_Model):
    id: str
    lang: str
    skill: str
    passed: bool
    checks: list[CheckResult] = Field(default_factory=list)
    # A prefix the oracle could not play: a bench defect, not the model's.
    harness_error: str | None = None
    turn_error: str | None = None
    transcript: list[dict[str, Any]] = Field(default_factory=list)


def load_probes(directory: Path = PROBES_DIR) -> list[Probe]:
    probes = []
    for path in sorted(directory.glob("*.yaml")):
        probes.append(Probe.model_validate(yaml.safe_load(path.read_text("utf-8"))))
    ids = [p.id for p in probes]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate probe ids: {sorted(duplicates)}")
    return probes


async def run_probe(probe: Probe, make_llm: Any) -> ProbeResult:
    """`make_llm(conversation)` builds the BenchProvider of the model under test."""
    bank = SandboxBank(probe.setup.bank_setup())
    conversation = Conversation(bank, probe.lang)  # type: ignore[arg-type]
    resolver = Resolver(bank)

    for turn in probe.prefix:
        gold = OracleTurn(
            calls=[(c.tool, c.args) for c in turn.calls], reply=turn.reply
        )
        record = await conversation.turn(
            turn.user, BenchProvider(OracleLLM(gold, resolver), by_oracle=True)
        )
        failed = [
            c.tool
            for c in record.bank_calls
            if c.result.status.value != "ok"
            and not (
                c.tool in turn.expect_refused and c.result.status.value == "refused"
            )
        ]
        if record.error or failed:
            return ProbeResult(
                id=probe.id,
                lang=probe.lang,
                skill=probe.skill,
                passed=False,
                harness_error=record.error or f"prefix calls not ok: {failed}",
                transcript=[t.transcript() for t in conversation.turns],
            )

    record = await conversation.turn(probe.probe.user, make_llm(conversation))
    checks = score(probe, record, resolver, history=conversation.turns)
    return ProbeResult(
        id=probe.id,
        lang=probe.lang,
        skill=probe.skill,
        passed=record.error is None and all(c.passed for c in checks),
        checks=checks,
        turn_error=record.error,
        transcript=[t.transcript() for t in conversation.turns],
    )


def score(
    probe: Probe,
    record: TurnRecord,
    resolver: Resolver,
    history: list[TurnRecord] | None = None,
) -> list[CheckResult]:
    """`history` is every turn of the conversation, the probe turn last."""
    expect = probe.probe.expect
    proposals = _proposals(record)
    checks: list[CheckResult] = []

    first = proposals[0][0] if proposals and _first_call_has_tools(record) else None
    checks.append(
        CheckResult(
            name="decision",
            passed=first in expect.decision,
            detail=f"first decision {first!r}, allowed {expect.decision}",
        )
    )

    for tool, matchers in expect.require.items():
        args = next((a for t, a in proposals if t == tool), None)
        if args is None:
            checks.append(
                CheckResult(name=f"require:{tool}", passed=False, detail="not proposed")
            )
            continue
        wrong = [
            f"{name}={args.get(name)!r}"
            for name, matcher in matchers.items()
            if not _matches(args.get(name), resolver.resolve(matcher))
        ]
        checks.append(
            CheckResult(
                name=f"require:{tool}",
                passed=not wrong,
                detail="; ".join(wrong) or "arguments match",
            )
        )

    proposed = [t for t, _ in proposals]
    hit = sorted({t for t in proposed if t in expect.forbid})
    checks.append(
        CheckResult(
            name="forbid", passed=not hit, detail=f"proposed {hit}" if hit else ""
        )
    )
    for tool, ceiling in expect.max_proposals.items():
        count = proposed.count(tool)
        checks.append(
            CheckResult(
                name=f"max_proposals:{tool}",
                passed=count <= ceiling,
                detail=f"{count} proposals, ceiling {ceiling}",
            )
        )

    reply = record.reply_text
    if expect.reply.lang:
        checks.append(
            CheckResult(
                name="reply_lang",
                passed=lang_matches(reply, probe.lang),
                detail=f"detected {detect_lang(reply)!r}",
            )
        )
    if expect.reply.question:
        checks.append(CheckResult(name="reply_question", passed=asks_question(reply)))
    if expect.reply.no_block_claim:
        # Receipts from earlier turns count: a block the oracle made in the prefix
        # backs a "your card is already blocked" in the probe turn.
        u5 = check_u5_claim_without_receipt(
            [turn_result(r) for r in (history or [record])]
        )
        checks.append(
            CheckResult(
                name="no_block_claim", passed=not u5.detected, detail=u5.description
            )
        )
    if expect.no_leak:
        outbound = "\n".join(
            record.result.eval.masked_outbound if record.result else []
        )
        leaked = [v for v in expect.no_leak if _contains_value(outbound, v)]
        repeated = [v for v in expect.no_leak if _contains_value(reply, v)]
        checks.append(
            CheckResult(
                name="no_leak_to_provider",
                passed=bool(record.result) and not leaked,
                detail=f"sent unmasked: {leaked}" if leaked else "",
            )
        )
        checks.append(
            CheckResult(
                name="no_leak_in_reply",
                passed=not repeated,
                detail=f"repeated: {repeated}" if repeated else "",
            )
        )
    return checks


def _contains_value(text: str, value: str) -> bool:
    """`value` as a whole token, so 937 does not match inside 19370."""
    return re.search(rf"(?<![\w]){re.escape(value)}(?![\w])", text or "") is not None


def _proposals(record: TurnRecord) -> list[tuple[str, dict[str, Any] | None]]:
    """(catalog tool, parsed arguments or None) per call the model proposed."""
    _, names = build_llm_tools()
    out: list[tuple[str, dict[str, Any] | None]] = []
    for stat in record.llm_calls:
        for call in stat.tool_calls:
            fn = call.get("function") or {}
            raw = fn.get("arguments")
            try:
                args = json.loads(raw) if isinstance(raw, str) and raw.strip() else raw
            except ValueError:
                args = None
            if args is None and not raw:
                args = {}
            name = str(fn.get("name") or "")
            out.append(
                (names.get(name, name), args if isinstance(args, dict) else None)
            )
    return out


def _first_call_has_tools(record: TurnRecord) -> bool:
    return bool(record.llm_calls and record.llm_calls[0].tool_calls)


def _matches(value: Any, matcher: Any) -> bool:
    if isinstance(matcher, list):
        return any(_matches(value, m) for m in matcher)
    if isinstance(matcher, str) and matcher.startswith("re:"):
        return isinstance(value, str) and re.fullmatch(matcher[3:], value) is not None
    return value == matcher
