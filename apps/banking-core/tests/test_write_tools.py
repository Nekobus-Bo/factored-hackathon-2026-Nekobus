"""DB-backed tests for the write tools (2B-3c) over the seed fixtures.

card.block: holder scoping (IDOR), policy flags propagated, the receipt re-read
from the database after commit, and idempotent re-block without a second write.
handoff.create: works in LOCKED without a holder, priority mapping, the four
structured elements assembled server-side, and the receipt re-read.
"""

import threading
import uuid
from collections.abc import Generator

import pytest
import sqlalchemy as sa
from banking_core.cards.tools import CardNotFoundError
from banking_core.cards.tools.card_block import (
    CardBlockResult,
)
from banking_core.cards.tools.card_block import (
    execute_card_block as _execute_card_block,
)
from banking_core.control.policy import Decision, PolicyConfig, PolicyEngine
from banking_core.control.session import SessionState
from banking_core.handoff.tools import (
    HandoffCreateResult,
    reread_handoff_create_result,
    resolve_priority,
)
from banking_core.handoff.tools import (
    execute_handoff_create as _execute_handoff_create,
)
from banking_core.models.core_bank import Card
from banking_core.models.ops import AuditLog, Handoff
from banking_core.seed.curated import load_curated_data
from banking_core.seed.fixtures import create_scenario_fixtures, fixture_uuid
from banking_core.seed.staging import (
    StagingAccount,
    StagingCard,
    StagingCustomer,
    StagingDataset,
    StagingTransaction,
)
from contracts.envelope import ReasonCode, ResourceState, VerificationState
from contracts.tools.card_block import BlockReason, CardBlockInput, CardBlockOutput
from contracts.tools.handoff_create import (
    Department,
    HandoffCreateInput,
    HandoffCreateOutput,
    HandoffOpenQuestion,
    HandoffPriority,
    HandoffReason,
    HandoffSummary,
)
from sqlalchemy.orm import Session, sessionmaker

ALLOWED = Decision(allowed=True)
SCOPE = "sess_write_tools_test"


def demo_holder(locale: str) -> uuid.UUID:
    return fixture_uuid(f"{locale}-demo-customer")


def execute_card_block(
    db_session: Session,
    holder_customer_id: str | uuid.UUID,
    args: CardBlockInput,
    policy_decision: Decision = ALLOWED,
    idempotency_scope: str = SCOPE,
) -> CardBlockResult:
    return _execute_card_block(
        db_session=db_session,
        holder_customer_id=holder_customer_id,
        args=args,
        policy_decision=policy_decision,
        idempotency_scope=idempotency_scope,
        verification_state_before=VerificationState.VERIFIED,
        verification_state_after=VerificationState.VERIFIED,
        session_id=idempotency_scope,
    )


def execute_handoff_create(
    db_session: Session,
    holder_customer_id: str | uuid.UUID | None,
    args: HandoffCreateInput,
    policy_decision: Decision,
    idempotency_scope: str,
    verification_state_before: VerificationState,
) -> HandoffCreateResult:
    return _execute_handoff_create(
        db_session=db_session,
        holder_customer_id=holder_customer_id,
        args=args,
        policy_decision=policy_decision,
        idempotency_scope=idempotency_scope,
        verification_state_before=verification_state_before,
        verification_state_after=VerificationState.HANDED_OFF,
        session_id=idempotency_scope,
    )


def card_by_ref(db: Session, card_ref: str) -> Card:
    db.expire_all()
    card = db.execute(sa.select(Card).where(Card.card_ref == card_ref)).scalar_one()
    return card


def block_audits(db: Session) -> list[AuditLog]:
    return list(
        db.scalars(
            sa.select(AuditLog)
            .where(AuditLog.action == "card.block")
            .order_by(AuditLog.id)
        )
    )


@pytest.fixture
def seeded(db_session: Session) -> Generator[Session, None, None]:
    bundle = create_scenario_fixtures()
    staging = StagingDataset(
        customers=[StagingCustomer.model_validate(c) for c in bundle.customers],
        accounts=[StagingAccount.model_validate(a) for a in bundle.accounts],
        cards=[StagingCard.model_validate(c) for c in bundle.cards],
        transactions=[
            StagingTransaction.model_validate(t) for t in bundle.transactions
        ],
    )
    load_curated_data(
        staging,
        session=db_session,
        master_key="00" * 32,
        blind_index_salt="test-salt-write-tools",
        force=True,
    )
    yield db_session
    db_session.rollback()
    db_session.execute(
        sa.text(
            "TRUNCATE TABLE ops.handoff, core_bank.transaction, core_bank.card, "
            "core_bank.account, core_bank.customer CASCADE"
        )
    )
    db_session.commit()


def test_card_block_writes_and_returns_receipt_re_read_from_db(
    seeded: Session,
) -> None:
    result = execute_card_block(
        seeded,
        demo_holder("es"),
        CardBlockInput(card_ref="card_demo_es", reason=BlockReason.UNRECOGNIZED_CHARGE),
        ALLOWED,
        SCOPE,
    )

    stored = card_by_ref(seeded, "card_demo_es")
    assert stored.status == "BLOCKED"
    assert stored.blocked_reason == BlockReason.UNRECOGNIZED_CHARGE
    [audit] = block_audits(seeded)

    receipt = result.output.receipt
    assert result.output.card_ref == "card_demo_es"
    assert receipt.action == "card.block"
    assert receipt.state_before == ResourceState.ACTIVE
    assert receipt.state_after == ResourceState.BLOCKED
    assert receipt.target_masked == "**** **** **** 1050"
    # Re-read, not built: the timestamp and audit id are the committed values.
    assert receipt.verified_at == stored.blocked_at
    assert receipt.audit_id == f"aud_{audit.id:08d}"
    assert audit.actor_ref == SCOPE
    assert audit.payload["card_state_before"] == "ACTIVE"
    assert CardBlockOutput.model_validate_json(result.output.model_dump_json())


@pytest.mark.parametrize("card_ref", ["card_demo_pt", "card_does_not_exist"])
def test_card_block_foreign_or_missing_card_is_indistinguishable(
    seeded: Session, card_ref: str
) -> None:
    """IDOR: another customer's card fails exactly like a missing one."""
    with pytest.raises(CardNotFoundError) as exc_info:
        execute_card_block(
            seeded,
            demo_holder("es"),
            CardBlockInput(card_ref=card_ref, reason=BlockReason.STOLEN),
            ALLOWED,
            SCOPE,
        )

    assert exc_info.value.args == (card_ref,)
    assert card_by_ref(seeded, "card_demo_pt").status == "ACTIVE"
    assert block_audits(seeded) == []


def test_card_block_re_block_is_idempotent_without_a_second_write(
    seeded: Session,
) -> None:
    args = CardBlockInput(card_ref="card_demo_en", reason=BlockReason.LOST)
    first = execute_card_block(seeded, demo_holder("en"), args, ALLOWED, SCOPE)
    blocked_at = card_by_ref(seeded, "card_demo_en").blocked_at

    again = execute_card_block(
        seeded,
        demo_holder("en"),
        CardBlockInput(card_ref="card_demo_en", reason=BlockReason.STOLEN),
        ALLOWED,
        SCOPE,
    )

    stored = card_by_ref(seeded, "card_demo_en")
    assert stored.blocked_at == blocked_at
    assert stored.blocked_reason == BlockReason.LOST
    assert again.output.receipt.state_before == ResourceState.BLOCKED
    assert again.output.receipt.state_after == ResourceState.BLOCKED
    assert again.output.receipt.verified_at == first.output.receipt.verified_at
    audits = block_audits(seeded)
    assert [a.payload["details"]["already_blocked"] for a in audits] == [False, True]


def test_card_block_on_seeded_blocked_card_keeps_original_block(
    seeded: Session,
) -> None:
    before = card_by_ref(seeded, "card_blocked_pt")
    result = execute_card_block(
        seeded,
        fixture_uuid("pt-blocked-customer"),
        CardBlockInput(card_ref="card_blocked_pt", reason=BlockReason.LOST),
        ALLOWED,
        SCOPE,
    )
    assert result.output.receipt.state_before == ResourceState.BLOCKED
    assert result.output.receipt.verified_at == before.blocked_at
    assert card_by_ref(seeded, "card_blocked_pt").blocked_reason == (
        BlockReason.SUSPICIOUS_ACTIVITY
    )


def test_card_block_propagates_policy_flags_and_is_not_refused_by_amount(
    seeded: Session,
) -> None:
    engine = PolicyEngine(
        PolicyConfig(
            thresholds_minor={"COP": 1000}, currency="COP", amount_mode="block"
        )
    )
    decision = engine.evaluate(
        tool="card.block",
        session=SessionState(session_id=SCOPE, state=VerificationState.VERIFIED),
        args={"card_ref": "card_demo_es", "reason": "UNRECOGNIZED_CHARGE"},
        context={"disputed_amount_minor": 35000000, "currency": "COP"},
    )
    assert decision.allowed is True
    assert decision.flags == ["POLICY_FLAGGED", "HANDOFF_REQUIRED", "PRIORITY"]

    result = execute_card_block(
        seeded,
        demo_holder("es"),
        CardBlockInput(card_ref="card_demo_es", reason=BlockReason.UNRECOGNIZED_CHARGE),
        decision,
        SCOPE,
    )

    assert result.output.receipt.state_after == ResourceState.BLOCKED
    assert result.flags == ["POLICY_FLAGGED", "HANDOFF_REQUIRED", "PRIORITY"]
    [audit] = block_audits(seeded)
    assert audit.payload["details"]["flags"] == result.flags
    assert audit.reason_code == ReasonCode.POLICY_FLAGGED.value


def test_card_block_refuses_a_disallowed_decision(seeded: Session) -> None:
    with pytest.raises(ValueError, match="allowed policy decision"):
        execute_card_block(
            seeded,
            demo_holder("es"),
            CardBlockInput(card_ref="card_demo_es", reason=BlockReason.LOST),
            Decision(allowed=False, reason_code=ReasonCode.STATE_NOT_ALLOWED),
            SCOPE,
        )
    assert card_by_ref(seeded, "card_demo_es").status == "ACTIVE"


HANDOFF_ARGS = HandoffCreateInput(
    reason=HandoffReason.DISPUTE_CLAIM,
    summary="Customer disputes a charge at Global Electronics Megastore.",
)


@pytest.mark.parametrize(
    ("requested", "flags", "state", "expected"),
    [
        (
            HandoffPriority.NORMAL,
            [],
            VerificationState.VERIFIED,
            HandoffPriority.NORMAL,
        ),
        (HandoffPriority.LOW, [], VerificationState.ANONYMOUS, HandoffPriority.LOW),
        (
            HandoffPriority.URGENT,
            [],
            VerificationState.VERIFIED,
            HandoffPriority.URGENT,
        ),
        (HandoffPriority.NORMAL, [], VerificationState.LOCKED, HandoffPriority.HIGH),
        (
            HandoffPriority.NORMAL,
            ["POLICY_FLAGGED", "HANDOFF_RECOMMENDED"],
            VerificationState.VERIFIED,
            HandoffPriority.NORMAL,
        ),
        (
            HandoffPriority.LOW,
            ["POLICY_FLAGGED", "HANDOFF_REQUIRED"],
            VerificationState.VERIFIED,
            HandoffPriority.HIGH,
        ),
        (
            HandoffPriority.NORMAL,
            ["POLICY_FLAGGED", "HANDOFF_REQUIRED", "PRIORITY"],
            VerificationState.VERIFIED,
            HandoffPriority.URGENT,
        ),
    ],
)
def test_handoff_priority_mapping(
    requested: HandoffPriority,
    flags: list[str],
    state: VerificationState,
    expected: HandoffPriority,
) -> None:
    decision = Decision(allowed=True, flags=flags)
    assert resolve_priority(requested, decision, state) == expected


def test_handoff_in_locked_session_without_holder_reaches_the_queue(
    seeded: Session,
) -> None:
    result = execute_handoff_create(
        seeded,
        None,
        HandoffCreateInput(
            reason=HandoffReason.CUSTOMER_LOCKED,
            summary="Customer locked out after failed OTP attempts.",
            department=Department.CUSTOMER_SUPPORT,
        ),
        ALLOWED,
        "sess_locked_1",
        VerificationState.LOCKED,
    )

    seeded.expire_all()
    [row] = seeded.scalars(sa.select(Handoff)).all()
    [audit] = seeded.scalars(
        sa.select(AuditLog).where(AuditLog.action == "handoff.create")
    ).all()
    assert row.customer_id is None
    assert row.priority == "HIGH" and result.priority == HandoffPriority.HIGH
    assert row.status == "QUEUED"
    receipt = result.output.receipt
    assert receipt.state_before == ResourceState.NONE
    assert receipt.state_after == ResourceState.QUEUED
    assert receipt.target_masked == row.handoff_ref == result.output.handoff_id
    assert receipt.verified_at == row.created_at == result.output.created_at
    assert receipt.audit_id == f"aud_{audit.id:08d}"
    assert result.output.queue_position == 1
    assert row.summary["verification_method"] == "locked_after_failed_verification"
    assert HandoffCreateOutput.model_validate_json(result.output.model_dump_json())
    assert result.output.priority == HandoffPriority.HIGH
    assert result.output.summary.model_dump(mode="json") == row.summary


def test_handoff_summary_has_four_elements_built_server_side(
    seeded: Session,
) -> None:
    scope = "sess_dispute_1"
    execute_card_block(
        seeded,
        demo_holder("es"),
        CardBlockInput(card_ref="card_demo_es", reason=BlockReason.UNRECOGNIZED_CHARGE),
        ALLOWED,
        scope,
    )
    decision = Decision(
        allowed=True,
        reason_code=ReasonCode.POLICY_FLAGGED,
        flags=["POLICY_FLAGGED", "HANDOFF_REQUIRED", "PRIORITY"],
    )

    result = execute_handoff_create(
        seeded,
        demo_holder("es"),
        HANDOFF_ARGS,
        decision,
        scope,
        VerificationState.VERIFIED,
    )

    seeded.expire_all()
    row = seeded.scalars(sa.select(Handoff)).one()
    assert row.customer_id == demo_holder("es")
    assert row.priority == "URGENT"
    summary = row.summary
    assert set(summary) == {
        "verified_facts",
        "actions_taken",
        "verification_method",
        "open_questions",
    }
    assert summary["verified_facts"] == {
        "verification_state": "VERIFIED",
        "customer_identified": True,
        "policy_flags": ["POLICY_FLAGGED", "HANDOFF_REQUIRED", "PRIORITY"],
    }
    assert [a["action"] for a in summary["actions_taken"]] == ["card.block"]
    assert summary["verification_method"] == "document_match_and_otp"
    assert summary["open_questions"] == [
        {"source": "model_unverified", "text": HANDOFF_ARGS.summary}
    ]
    # The model's free text never reaches the audit log.
    audit = seeded.scalars(
        sa.select(AuditLog).where(AuditLog.action == "handoff.create")
    ).one()
    assert HANDOFF_ARGS.summary not in str(audit.payload)
    assert audit.payload["handoff_priority"] == "URGENT"
    assert result.output.receipt.state_after == ResourceState.QUEUED
    assert result.output.priority == HandoffPriority.URGENT
    assert result.output.summary.model_dump(mode="json") == summary


def test_handoff_queue_position_follows_priority(seeded: Session) -> None:
    first = execute_handoff_create(
        seeded, None, HANDOFF_ARGS, ALLOWED, "sess_q1", VerificationState.ANONYMOUS
    )
    urgent = execute_handoff_create(
        seeded,
        None,
        HANDOFF_ARGS,
        Decision(allowed=True, flags=["PRIORITY"]),
        "sess_q2",
        VerificationState.ANONYMOUS,
    )
    assert first.output.queue_position == 1
    assert urgent.output.queue_position == 1
    assert len({first.output.handoff_id, urgent.output.handoff_id}) == 2


def test_handoff_refuses_a_disallowed_decision(seeded: Session) -> None:
    with pytest.raises(ValueError, match="allowed policy decision"):
        execute_handoff_create(
            seeded,
            None,
            HANDOFF_ARGS,
            Decision(allowed=False, reason_code=ReasonCode.POLICY_BLOCKED),
            "sess_x",
            VerificationState.LOCKED,
        )
    assert seeded.scalars(sa.select(Handoff)).all() == []


def test_handoff_reread_refreshes_server_priority_and_summary(
    seeded: Session,
) -> None:
    args = HandoffCreateInput(
        reason=HandoffReason.DISPUTE_CLAIM,
        summary="The model asks for a dispute review.",
        priority=HandoffPriority.LOW,
        department=Department.DISPUTES,
    )
    result = execute_handoff_create(
        seeded,
        demo_holder("es"),
        args,
        Decision(allowed=True, flags=["HANDOFF_REQUIRED"]),
        "sess_handoff_reread",
        VerificationState.VERIFIED,
    )
    seeded.expire_all()
    stored = seeded.scalars(sa.select(Handoff)).one()
    stale_output = result.output.model_copy(
        update={
            "priority": HandoffPriority.LOW,
            "summary": HandoffSummary(
                verified_facts={"verification_state": "ANONYMOUS"},
                actions_taken=[],
                verification_method="model-authored",
                open_questions=[
                    HandoffOpenQuestion(
                        source="model_unverified", text="stale model summary"
                    )
                ],
            ),
        }
    )

    refreshed = reread_handoff_create_result(seeded, stale_output)

    assert stored.priority == "HIGH"
    assert refreshed.output.priority is HandoffPriority.HIGH
    assert refreshed.priority is HandoffPriority.HIGH
    assert refreshed.output.summary.model_dump(mode="json") == stored.summary
    assert refreshed.output.summary.open_questions[0].text == args.summary


def _handoff_audits(db: Session, session_ref: str) -> list[AuditLog]:
    db.expire_all()
    return list(
        db.scalars(
            sa.select(AuditLog)
            .where(AuditLog.action == "handoff.create")
            .where(AuditLog.actor_ref == session_ref)
            .order_by(AuditLog.id)
        )
    )


def test_second_handoff_in_a_session_returns_the_open_one(seeded: Session) -> None:
    scope = "sess_handoff_twice"
    first = execute_handoff_create(
        seeded,
        demo_holder("es"),
        HANDOFF_ARGS,
        Decision(allowed=True, flags=["HANDOFF_REQUIRED"]),
        scope,
        VerificationState.VERIFIED,
    )

    again = execute_handoff_create(
        seeded,
        demo_holder("es"),
        HandoffCreateInput(
            reason=HandoffReason.CUSTOMER_REQUEST,
            summary="Second request, phrased differently.",
            priority=HandoffPriority.URGENT,
            department=Department.DISPUTES,
        ),
        ALLOWED,
        scope,
        VerificationState.HANDED_OFF,
    )

    seeded.expire_all()
    [row] = seeded.scalars(sa.select(Handoff)).all()
    assert again.output.handoff_id == first.output.handoff_id == row.handoff_ref
    # What was queued is what is returned: the second call changes nothing.
    assert again.output.priority == first.output.priority == HandoffPriority.HIGH
    assert again.output.department == first.output.department == row.department
    assert again.output.summary.model_dump(mode="json") == row.summary
    assert again.output.queue_position == first.output.queue_position
    receipt = again.output.receipt
    assert receipt.target_masked == row.handoff_ref
    assert (receipt.state_before, receipt.state_after) == (
        ResourceState.QUEUED,
        ResourceState.QUEUED,
    )
    assert receipt.verified_at == row.created_at
    # Still audited: one row per call, the second one pointing at the open handoff.
    first_audit, second_audit = _handoff_audits(seeded, scope)
    assert first.output.receipt.audit_id == f"aud_{first_audit.id:08d}"
    assert receipt.audit_id == f"aud_{second_audit.id:08d}"
    assert second_audit.decision == "allowed"
    assert second_audit.payload["details"]["already_open"] is True
    assert second_audit.payload["details"]["handoff_ref"] == row.handoff_ref
    assert second_audit.payload["handoff_status"] == "QUEUED"
    assert "already_open" not in first_audit.payload["details"]
    assert "Second request" not in str(second_audit.payload)
    # The dispatcher's post-commit re-read agrees with what was returned.
    reread = reread_handoff_create_result(seeded, again.output)
    assert reread.output.model_dump(mode="json") == again.output.model_dump(mode="json")


def test_open_handoff_of_another_session_is_not_reused(seeded: Session) -> None:
    mine = execute_handoff_create(
        seeded, None, HANDOFF_ARGS, ALLOWED, "sess_mine", VerificationState.ANONYMOUS
    )
    other = execute_handoff_create(
        seeded, None, HANDOFF_ARGS, ALLOWED, "sess_other", VerificationState.ANONYMOUS
    )

    assert mine.output.handoff_id != other.output.handoff_id
    assert len(seeded.scalars(sa.select(Handoff)).all()) == 2


def test_parallel_handoffs_in_one_session_queue_a_single_row(
    seeded: Session, db_engine: sa.Engine
) -> None:
    """The per-session lock holds even without the dispatcher's Redis lock."""
    scope = "sess_handoff_parallel"
    session_maker = sessionmaker(bind=db_engine, autoflush=False)
    barrier = threading.Barrier(6)
    handoff_ids: list[str] = []
    failures: list[BaseException] = []

    def create() -> None:
        try:
            with session_maker() as db:
                barrier.wait()
                result = execute_handoff_create(
                    db,
                    None,
                    HANDOFF_ARGS,
                    ALLOWED,
                    scope,
                    VerificationState.ANONYMOUS,
                )
                handoff_ids.append(result.output.handoff_id)
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assertion
            failures.append(exc)

    threads = [threading.Thread(target=create) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    assert len(set(handoff_ids)) == 1 and len(handoff_ids) == 6
    seeded.expire_all()
    assert len(seeded.scalars(sa.select(Handoff)).all()) == 1
    assert len(_handoff_audits(seeded, scope)) == 6
