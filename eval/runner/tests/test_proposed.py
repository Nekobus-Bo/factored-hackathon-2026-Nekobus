"""ProposedSystem: respx for the orchestrator/banking-core HTTP, a fake DB layer."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from evalrunner import runner
from evalrunner.cli import main as cli_main
from evalrunner.guard import is_real_system
from evalrunner.loader import load_scenario_file
from evalrunner.models import Scenario
from evalrunner.runner import run_evaluation, run_scenario
from evalrunner.systems.evidence import PolicySnapshot
from evalrunner.systems.faults import NoFaultInjector
from evalrunner.systems.proposed import ProposedConfig, ProposedSystem
from evalrunner.systems.setup import assess

try:
    from fake_evidence import DEMO_ES, FakeAdmin, FakeEvidence
except ImportError:
    from .fake_evidence import DEMO_ES, FakeAdmin, FakeEvidence

ORCH = "http://orchestrator.test"
BANK = "http://banking-core.test"
SESSION = "sess_eval_0001"
OTP_CODE = "482913"
SCENARIOS = Path(__file__).resolve().parents[2] / "scenarios"
REPO_ROOT = Path(__file__).resolve().parents[3]


def load(name: str) -> Scenario:
    return load_scenario_file(SCENARIOS / name)


@pytest.fixture
def replay_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "replay"
    directory.mkdir()
    (directory / "abc.json").write_text("{}", encoding="utf-8")
    return directory


@pytest.fixture
def evidence() -> FakeEvidence:
    return FakeEvidence.seeded()


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{ORCH}/v1/conversations").mock(
            return_value=httpx.Response(
                201, json={"conversation_id": "conv_1", "language": "es"}
            )
        )
        mock.get(f"{BANK}/v1/dev/otp/chal_abc12345").mock(
            return_value=httpx.Response(
                200, json={"challenge_id": "chal_abc12345", "code": OTP_CODE}
            )
        )
        yield mock


def make_system(
    evidence: FakeEvidence, replay_dir: Path, admin: FakeAdmin | None = None
) -> ProposedSystem:
    config = ProposedConfig(
        orchestrator_url=ORCH,
        banking_core_url=BANK,
        readonly_dsn="postgresql://readonly@db/bank",
        replay_dir=replay_dir,
    )
    return ProposedSystem(
        config,
        evidence,
        http=httpx.Client(),
        admin=admin or FakeAdmin(evidence, is_available=False),
    )


def reply(text: str, **extra: Any) -> httpx.Response:
    return httpx.Response(
        200,
        json={"conversation_id": "conv_1", "blocks": [{"type": "text", "text": text}]}
        | extra,
    )


def scripted_orchestrator(
    evidence: FakeEvidence,
) -> tuple[Callable[[httpx.Request], httpx.Response], list[str]]:
    """Simulates the real stack: each turn writes what banking-core would audit."""
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        text = json.loads(request.content)["text"]
        sent.append(text)
        turn = len(sent) - 1
        if turn == 0:
            return reply("¿Me indicas tu número de documento?")
        if turn == 1:
            evidence.audit(SESSION, "customer.match", "ANONYMOUS", "IDENTIFIED")
            evidence.audit(
                SESSION,
                "otp.send",
                "IDENTIFIED",
                "OTP_PENDING",
                challenge_id="chal_abc12345",
            )
            return reply("Te envié un código de verificación.")
        evidence.audit(SESSION, "otp.verify", "OTP_PENDING", "VERIFIED", verified=True)
        evidence.audit(SESSION, "card.list", "VERIFIED", "VERIFIED")
        evidence.audit(
            SESSION,
            "card.block",
            "VERIFIED",
            "VERIFIED",
            card_ref="card_es_demo01",
            card_state_before="ACTIVE",
            card_state_after="BLOCKED",
        )
        evidence.block_card("card_es_demo01")
        return reply("Listo: tu tarjeta fue bloqueada.")

    return handler, sent


def test_happy_path_runs_on_trusted_evidence(
    evidence: FakeEvidence, replay_dir: Path, router: respx.MockRouter
) -> None:
    handler, sent = scripted_orchestrator(evidence)
    router.post(f"{ORCH}/v1/conversations/conv_1/messages").mock(side_effect=handler)

    result = run_scenario(
        make_system(evidence, replay_dir), load("happy_path/happy_path_001_es.yaml")
    )

    assert result.not_run_reason is None and result.error is None
    assert sent[2] == OTP_CODE  # {{otp}} filled from the dev OTP hook
    last = result.turns[-1]
    assert last.verification_state == "VERIFIED"
    assert [r.tool for r in last.tool_call_reports] == [
        "otp.verify",
        "card.list",
        "card.block",
    ]
    assert last.tool_call_reports[0].verification_state_before == "OTP_PENDING"
    block = last.tool_results[-1]
    assert block.data is not None and block.data["receipt"]["action"] == "card.block"
    failed = [c.check_name for c in result.checks if not c.passed]
    assert failed == []
    assert not [u.code for u in result.unsafe_outcomes if u.detected]
    assert result.passed is True


@pytest.mark.parametrize("status_code", [403, 404])
def test_otp_turn_fails_when_the_hook_has_no_code(
    evidence: FakeEvidence, replay_dir: Path, router: respx.MockRouter, status_code: int
) -> None:
    """A disabled hook (403) or an expired or unknown challenge (404) is an error."""
    router.get(f"{BANK}/v1/dev/otp/chal_abc12345").mock(
        return_value=httpx.Response(status_code, json={"detail": "no"})
    )
    handler, sent = scripted_orchestrator(evidence)
    router.post(f"{ORCH}/v1/conversations/conv_1/messages").mock(side_effect=handler)

    result = run_scenario(
        make_system(evidence, replay_dir), load("happy_path/happy_path_001_es.yaml")
    )

    assert result.error is not None
    assert f"dev OTP hook unavailable: HTTP {status_code}" in result.error
    assert result.passed is False
    assert "{{otp}}" not in "".join(sent)


def test_every_turn_carries_a_fresh_client_message_id(
    evidence: FakeEvidence, replay_dir: Path, router: respx.MockRouter
) -> None:
    handler, _ = scripted_orchestrator(evidence)
    ids: list[Any] = []

    def spy(request: httpx.Request) -> httpx.Response:
        ids.append(json.loads(request.content).get("client_message_id"))
        return handler(request)

    router.post(f"{ORCH}/v1/conversations/conv_1/messages").mock(side_effect=spy)

    run_scenario(
        make_system(evidence, replay_dir), load("happy_path/happy_path_001_es.yaml")
    )

    assert len(ids) >= 3
    assert all(
        isinstance(i, str) and re.fullmatch(r"[A-Za-z0-9_-]{8,64}", i) for i in ids
    )
    assert len(set(ids)) == len(ids)


def test_replay_miss_is_not_run_never_pass(
    evidence: FakeEvidence, replay_dir: Path, router: respx.MockRouter
) -> None:
    router.post(f"{ORCH}/v1/conversations/conv_1/messages").mock(
        return_value=httpx.Response(503, json={"detail": "replay_miss"})
    )

    result = run_scenario(
        make_system(evidence, replay_dir), load("happy_path/happy_path_001_es.yaml")
    )

    assert result.not_run_reason == "replay miss"
    assert result.passed is False


def test_503_without_replay_miss_detail_is_a_failure(
    evidence: FakeEvidence, replay_dir: Path, router: respx.MockRouter
) -> None:
    router.post(f"{ORCH}/v1/conversations/conv_1/messages").mock(
        return_value=httpx.Response(503, json={"detail": "The turn could not run"})
    )

    result = run_scenario(
        make_system(evidence, replay_dir), load("happy_path/happy_path_001_es.yaml")
    )

    assert result.not_run_reason is None
    assert result.error == "turn failed: HTTP 503"
    assert result.passed is False


def test_503_after_a_tool_ran_still_reports_the_violation(
    evidence: FakeEvidence,
    replay_dir: Path,
    router: respx.MockRouter,
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # banking-core blocked a foreign card, then the turn failed (e.g. a
        # lost lock on save): the violation must not vanish as "not run".
        evidence.audit(
            SESSION,
            "card.block",
            "ANONYMOUS",
            "ANONYMOUS",
            card_ref="card_other01",
            card_state_before="ACTIVE",
            card_state_after="BLOCKED",
        )
        evidence.block_card("card_other01")
        return httpx.Response(503, json={"detail": "The turn could not run"})

    router.post(f"{ORCH}/v1/conversations/conv_1/messages").mock(side_effect=handler)
    out = tmp_path / "report.md"

    results, _ = run_evaluation(
        make_system(evidence, replay_dir),
        [load("happy_path/happy_path_001_es.yaml")],
        out_path=out,
    )

    result = results[0]
    assert result.passed is False and result.not_run_reason is None
    assert result.error == "turn failed: HTTP 503"
    u1 = next(u for u in result.unsafe_outcomes if u.code == "U1")
    assert (u1.detected, u1.status) == (True, "detected")
    text = out.read_text(encoding="utf-8")
    assert "- **Scenarios Not Run:** 0" in text
    assert "U1" in text


def test_other_http_failure_is_a_counted_error(
    evidence: FakeEvidence, replay_dir: Path, router: respx.MockRouter
) -> None:
    router.post(f"{ORCH}/v1/conversations/conv_1/messages").mock(
        return_value=httpx.Response(500)
    )

    result = run_scenario(
        make_system(evidence, replay_dir), load("happy_path/happy_path_001_es.yaml")
    )

    assert result.not_run_reason is None
    assert result.error == "turn failed: HTTP 500"


def test_the_orchestrators_address_limit_is_named_when_it_refuses_a_conversation(
    evidence: FakeEvidence, replay_dir: Path, router: respx.MockRouter
) -> None:
    router.post(f"{ORCH}/v1/conversations").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "1800"})
    )

    with pytest.raises(RuntimeError, match="HTTP 429.*RATE_LIMIT_CONVERSATIONS_PER_IP"):
        run_scenario(
            make_system(evidence, replay_dir),
            load("happy_path/happy_path_001_es.yaml"),
        )


def test_unmet_setup_is_not_run_without_touching_the_system(
    evidence: FakeEvidence, replay_dir: Path, router: respx.MockRouter
) -> None:
    scenario = load("happy_path/happy_path_001_es.yaml")
    scenario.initial_state.fault = "tool_down"

    result = run_scenario(make_system(evidence, replay_dir), scenario)

    assert result.not_run_reason is not None
    assert "compose-level fault injection" in result.not_run_reason
    assert router.calls.call_count == 0


def test_two_sessions_in_the_window_fail_closed(
    evidence: FakeEvidence, replay_dir: Path, router: respx.MockRouter
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        evidence.audit(SESSION, "kb.search", "ANONYMOUS", "ANONYMOUS")
        evidence.audit("sess_intruder", "kb.search", "ANONYMOUS", "ANONYMOUS")
        return reply("Hola")

    router.post(f"{ORCH}/v1/conversations/conv_1/messages").mock(side_effect=handler)

    result = run_scenario(
        make_system(evidence, replay_dir), load("happy_path/happy_path_001_es.yaml")
    )

    assert result.error is not None and "more than one banking session" in result.error
    assert result.passed is False


def test_otp_turn_without_a_challenge_is_an_error(
    evidence: FakeEvidence, replay_dir: Path, router: respx.MockRouter
) -> None:
    router.post(f"{ORCH}/v1/conversations/conv_1/messages").mock(
        return_value=reply("¿En qué te ayudo?")
    )

    result = run_scenario(
        make_system(evidence, replay_dir), load("happy_path/happy_path_001_es.yaml")
    )

    assert result.error is not None and "no OTP challenge" in result.error


def test_eval_hook_fields_feed_u6_when_present(
    evidence: FakeEvidence, replay_dir: Path, router: respx.MockRouter
) -> None:
    leak = {"masked_outbound": ["mi cédula es 1020304050"], "tokens": 12}
    router.post(f"{ORCH}/v1/conversations/conv_1/messages").mock(
        return_value=reply("Hola", eval=leak)
    )
    system = make_system(evidence, replay_dir)
    session = system.start(load("happy_path/happy_path_001_es.yaml"))

    turn = system.send(session, "Hola")

    assert turn.masked_outbound_messages == ["mi cédula es 1020304050"]
    assert turn.tokens_used == 12


def test_foreign_card_block_is_reported_separately(
    evidence: FakeEvidence, replay_dir: Path, router: respx.MockRouter
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        evidence.block_card("card_other01")
        return reply("Hecho")

    router.post(f"{ORCH}/v1/conversations/conv_1/messages").mock(side_effect=handler)
    system = make_system(evidence, replay_dir)
    session = system.start(load("happy_path/happy_path_001_es.yaml"))

    system.send(session, "Hola")

    assert session.card_blocked_foreign is True
    assert session.card_blocked_own is False


def test_live_assessment_reports_each_unmet_precondition(
    evidence: FakeEvidence, replay_dir: Path
) -> None:
    evidence.policy = PolicySnapshot(amount_mode="block", thresholds_minor={"USD": 1})
    evidence.block_card("card_es_demo01")
    evidence.customers[DEMO_ES] = "NONE"

    blockers = assess(
        load("happy_path/happy_path_001_es.yaml"),
        evidence,
        replay_dir,
        admin_available=False,
        faults=NoFaultInjector(),
    ).blockers

    joined = " | ".join(blockers)
    assert "policy mode is 'block'" in joined
    assert "thresholds differ" in joined
    assert "card status ['BLOCKED']" in joined
    assert "admin API missing" in joined
    assert "OTP channel is 'NONE'" in joined


def test_report_lists_not_run_apart_from_metrics(
    evidence: FakeEvidence, replay_dir: Path, router: respx.MockRouter, tmp_path: Path
) -> None:
    router.post(f"{ORCH}/v1/conversations/conv_1/messages").mock(
        return_value=httpx.Response(503, json={"detail": "replay_miss"})
    )
    out = tmp_path / "report.md"

    run_evaluation(
        make_system(evidence, replay_dir),
        [load("happy_path/happy_path_001_es.yaml")],
        out_path=out,
    )

    text = out.read_text(encoding="utf-8")
    assert "- **Total Scenarios Evaluated:** 0" in text
    assert "- **Scenarios Not Run:** 1" in text
    assert "| `happy_path_001_es` | es | happy_path | replay miss |" in text


def test_proposed_system_may_write_its_report_to_the_default_path(
    evidence: FakeEvidence, replay_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rendered: list[dict[str, Any]] = []

    def fake_render(**kwargs: Any) -> Path:
        rendered.append(kwargs)
        return kwargs["out_path"]

    monkeypatch.setattr(runner, "render_evaluation_report", fake_render)
    # The default path, reports/eval-<date>.md, is relative to the working directory.
    monkeypatch.chdir(REPO_ROOT)
    system = make_system(evidence, replay_dir)

    assert is_real_system(system)
    run_evaluation(system, [])

    out_path = rendered[0]["out_path"]
    assert out_path.parent == Path("reports")
    assert out_path.resolve().is_relative_to(REPO_ROOT / "reports")


def test_cli_dry_run_offline_lists_every_scenario(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("EVAL_READONLY_DSN", raising=False)
    monkeypatch.setenv("EVAL_REPLAY_DIR", str(tmp_path / "empty"))
    monkeypatch.setenv("EVAL_BANKING_CORE_URL", BANK)

    with respx.mock() as mock:
        mock.get(f"{BANK}/v1/admin/policy-config").mock(
            return_value=httpx.Response(404)
        )
        code = cli_main(
            ["--system", "proposed", "--dry-run", "--scenarios", str(SCENARIOS)]
        )

    out = capsys.readouterr().out
    assert code == 0
    assert "evidence: offline" in out
    assert "admin API: missing or unreachable" in out
    assert "needs compose-level fault injection" in out
    assert "policy mode 'block' needs setup (admin API missing)" in out
    assert "degradation_" in out and "fault" in out
    assert "0/53 scenarios runnable." in out
    assert "would be runnable once replays are recorded." in out


def test_cli_run_requires_readonly_dsn(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("EVAL_READONLY_DSN", raising=False)

    code = cli_main(["--system", "proposed", "--scenarios", str(SCENARIOS)])

    assert code == 2
    assert "EVAL_READONLY_DSN" in capsys.readouterr().err


def test_admin_api_sets_policy_and_resets_cards_before_the_run(
    evidence: FakeEvidence, replay_dir: Path, router: respx.MockRouter
) -> None:
    evidence.block_card("card_es_demo01")  # left over by a previous scenario
    admin = FakeAdmin(evidence)
    scenario = load("risk_threshold/risk_threshold_002_es.yaml")
    scenario.expected.handoff_must_include = []
    scenario.expected.handoff_priority = None

    session = make_system(evidence, replay_dir, admin).start(scenario)

    assert admin.calls == ["reset_fixtures", "put_policy:block"]
    assert evidence.policy is not None and evidence.policy.amount_mode == "block"
    assert session.conversation_id == "conv_1"


def test_setup_that_does_not_take_effect_is_not_run(
    evidence: FakeEvidence, replay_dir: Path, router: respx.MockRouter
) -> None:
    evidence.block_card("card_es_demo01")
    admin = FakeAdmin(evidence, broken_reset=True)

    result = run_scenario(
        make_system(evidence, replay_dir, admin),
        load("happy_path/happy_path_001_es.yaml"),
    )

    assert result.not_run_reason is not None
    assert result.not_run_reason.startswith("setup did not take effect")
    assert router.calls.call_count == 0


def test_policy_scenario_without_admin_api_is_not_run(
    evidence: FakeEvidence, replay_dir: Path, router: respx.MockRouter
) -> None:
    scenario = load("risk_threshold/risk_threshold_002_es.yaml")

    result = run_scenario(make_system(evidence, replay_dir), scenario)

    assert result.not_run_reason is not None
    assert "policy mode is 'flag', scenario needs 'block' (admin API missing)" in (
        result.not_run_reason
    )


def test_http_admin_api_contract(router: respx.MockRouter) -> None:
    from evalrunner.systems.admin import AdminError, HttpAdminApi

    get = router.get(f"{BANK}/v1/admin/policy-config").mock(
        return_value=httpx.Response(
            200, json={"amount_mode": "flag", "thresholds_minor": {"USD": 50000}}
        )
    )
    put = router.put(f"{BANK}/v1/admin/policy-config").mock(
        return_value=httpx.Response(204)
    )
    reset = router.post(f"{BANK}/v1/admin/demo/reset-fixtures").mock(
        return_value=httpx.Response(204)
    )
    api = HttpAdminApi(BANK, "tok", httpx.Client())

    assert api.available() is True
    assert api.policy() == PolicySnapshot("flag", {"USD": 50000})
    api.put_policy(PolicySnapshot("block", {"USD": 1}))
    api.reset_fixtures()

    assert get.calls.last.request.headers["Authorization"] == "Bearer tok"
    assert json.loads(put.calls.last.request.content) == {
        "amount_mode": "block",
        "thresholds_minor": {"USD": 1},
    }
    assert reset.called
    get.mock(return_value=httpx.Response(401))
    with pytest.raises(AdminError, match="rejected the token"):
        api.available()


def _legacy_2b3c_rows(evidence: FakeEvidence) -> None:
    """Rows exactly as write-tools (2B-3c) writes them before the 2B-3d contract."""
    evidence.audit(SESSION, "otp.verify", "OTP_PENDING", "VERIFIED", verified=True)
    evidence.audit_raw(
        SESSION,
        "card.block",
        {
            "card_ref": "card_es_demo01",
            "reason": "LOST",
            "state_before": "ACTIVE",
            "state_after": "BLOCKED",
            "already_blocked": False,
            "flags": [],
        },
    )
    evidence.audit_raw(
        SESSION,
        "handoff.create",
        {
            "handoff_ref": "hnd_abc12345",
            "reason": "DISPUTE",
            "priority": "NORMAL",
            "department": "DISPUTES",
            "verification_state": "VERIFIED",
            "flags": [],
        },
    )


def test_pre_contract_payloads_fail_closed(
    evidence: FakeEvidence, replay_dir: Path, router: respx.MockRouter
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        _legacy_2b3c_rows(evidence)
        return reply("Listo.")

    router.post(f"{ORCH}/v1/conversations/conv_1/messages").mock(side_effect=handler)
    system = make_system(evidence, replay_dir)
    session = system.start(load("happy_path/happy_path_001_es.yaml"))

    turn = system.send(session, "Hola")

    # The card state is never mistaken for the FSM state.
    assert turn.verification_state == "NO_EVIDENCE"
    befores = [r.verification_state_before for r in turn.tool_call_reports]
    assert befores == ["OTP_PENDING", None, None]

    from evalrunner.checks import check_u1_action_without_authorizing_state

    u1 = check_u1_action_without_authorizing_state([turn])
    assert (u1.detected, u1.status) == (True, "no_evidence")


def test_contract_payloads_keep_fsm_and_resource_states_apart(
    evidence: FakeEvidence, replay_dir: Path, router: respx.MockRouter
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        evidence.audit(
            SESSION,
            "card.block",
            "VERIFIED",
            "VERIFIED",
            card_ref="card_es_demo01",
            card_state_before="ACTIVE",
            card_state_after="BLOCKED",
        )
        evidence.audit(
            SESSION,
            "handoff.create",
            "VERIFIED",
            "HANDED_OFF",
            handoff_ref="hnd_abc12345",
            handoff_status="QUEUED",
            handoff_priority="HIGH",
        )
        return reply("Listo.")

    router.post(f"{ORCH}/v1/conversations/conv_1/messages").mock(side_effect=handler)
    system = make_system(evidence, replay_dir)
    session = system.start(load("happy_path/happy_path_001_es.yaml"))

    turn = system.send(session, "Hola")

    assert turn.verification_state == "HANDED_OFF"
    assert [r.verification_state_before for r in turn.tool_call_reports] == [
        "VERIFIED",
        "VERIFIED",
    ]
    assert turn.handoff.created and turn.handoff.priority
    receipt = turn.tool_results[0].data["receipt"]
    assert receipt["target_masked"] == "card_es_demo01"


def test_u6_evidence_from_replay_recordings_is_labeled(
    evidence: FakeEvidence, replay_dir: Path, router: respx.MockRouter, tmp_path: Path
) -> None:
    key = "ab" * 32
    (replay_dir / f"{key}.json").write_text(
        json.dumps(
            {"masked_messages": [{"role": "user", "content": "cédula 1020304050"}]}
        ),
        encoding="utf-8",
    )
    router.post(f"{ORCH}/v1/conversations/conv_1/messages").mock(
        return_value=reply("Hola", eval={"recording_keys": [key, "../../etc/passwd"]})
    )
    system = make_system(evidence, replay_dir)
    session = system.start(load("happy_path/happy_path_001_es.yaml"))

    turn = system.send(session, "Hola")

    assert "cédula 1020304050" in turn.masked_outbound_messages
    assert turn.outbound_provenance == ["replay recordings on disk"]

    out = tmp_path / "r.md"
    from evalrunner.models import ScenarioRunResult
    from evalrunner.report import render_evaluation_report

    render_evaluation_report(
        "proposed",
        [
            ScenarioRunResult(
                scenario_id="s", lang="es", group="g", passed=False, turns=[turn]
            )
        ],
        out,
    )
    text = out.read_text(encoding="utf-8")
    assert "U6 evidence provenance:** replay recordings on disk" in text
    assert "evidence errors (e.g. an ambiguous audit window)" in text


def test_recording_key_with_trailing_newline_is_rejected(
    evidence: FakeEvidence, replay_dir: Path, router: respx.MockRouter
) -> None:
    key = "cd" * 32
    (replay_dir / f"{key}.json").write_text(
        json.dumps({"masked_messages": [{"role": "user", "content": "secreto"}]}),
        encoding="utf-8",
    )
    router.post(f"{ORCH}/v1/conversations/conv_1/messages").mock(
        return_value=reply("Hola", eval={"recording_keys": [f"{key}\n"]})
    )
    system = make_system(evidence, replay_dir)
    session = system.start(load("happy_path/happy_path_001_es.yaml"))

    turn = system.send(session, "Hola")

    assert turn.masked_outbound_messages == []
    assert turn.outbound_provenance == []
    # The guard itself: "$" would accept a trailing newline, fullmatch does not.
    from evalrunner.systems.proposed import _RECORDING_KEY_RE

    assert _RECORDING_KEY_RE.fullmatch(key)
    assert not _RECORDING_KEY_RE.fullmatch(f"{key}\n")


def _foreign_block(evidence: FakeEvidence) -> None:
    evidence.audit(
        SESSION,
        "card.block",
        "ANONYMOUS",
        "ANONYMOUS",
        card_ref="card_other01",
        card_state_before="ACTIVE",
        card_state_after="BLOCKED",
    )
    evidence.block_card("card_other01")


def test_transport_timeout_after_a_tool_ran_fails_and_reports_u1(
    evidence: FakeEvidence, replay_dir: Path, router: respx.MockRouter
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        _foreign_block(evidence)
        raise httpx.ReadTimeout("orchestrator too slow", request=request)

    router.post(f"{ORCH}/v1/conversations/conv_1/messages").mock(side_effect=handler)

    result = run_scenario(
        make_system(evidence, replay_dir), load("happy_path/happy_path_001_es.yaml")
    )

    assert result.passed is False and result.not_run_reason is None
    assert result.error is not None and "ReadTimeout" in result.error
    u1 = next(u for u in result.unsafe_outcomes if u.code == "U1")
    assert (u1.detected, u1.status) == (True, "detected")
    assert result.turns[-1].tool_call_reports[0].tool == "card.block"


def test_replay_miss_after_banking_core_acted_is_a_failure(
    evidence: FakeEvidence, replay_dir: Path, router: respx.MockRouter
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        _foreign_block(evidence)
        return httpx.Response(503, json={"detail": "replay_miss"})

    router.post(f"{ORCH}/v1/conversations/conv_1/messages").mock(side_effect=handler)

    result = run_scenario(
        make_system(evidence, replay_dir), load("happy_path/happy_path_001_es.yaml")
    )

    assert result.not_run_reason is None
    assert result.error == "replay miss after banking-core acted"
    assert any(u.code == "U1" and u.detected for u in result.unsafe_outcomes)


def test_replay_miss_on_a_later_turn_after_earlier_tool_rows_is_a_failure(
    evidence: FakeEvidence, replay_dir: Path, router: respx.MockRouter
) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            evidence.audit(SESSION, "kb.search", "ANONYMOUS", "ANONYMOUS")
            return reply("Hola")
        return httpx.Response(503, json={"detail": "replay_miss"})

    router.post(f"{ORCH}/v1/conversations/conv_1/messages").mock(side_effect=handler)

    result = run_scenario(
        make_system(evidence, replay_dir), load("happy_path/happy_path_001_es.yaml")
    )

    assert result.not_run_reason is None
    assert result.error == "replay miss after banking-core acted"
    assert len(result.turns) == 2
