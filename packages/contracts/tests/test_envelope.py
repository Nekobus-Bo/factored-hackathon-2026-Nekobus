"""Tests for common envelopes (ToolCall, ToolResult, Receipt).

Includes Reviewer probe rejections, strict argument typing, and idempotency enforcement.
"""

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from contracts.envelope import (
    MUTATING_TOOLS,
    WRITE_TOOLS,
    ReasonCode,
    Receipt,
    ResourceState,
    ToolCall,
    ToolResult,
    ToolResultStatus,
    VerificationState,
)
from contracts.tools import (
    CODE_FLOOR,
    TOOL_CATALOG,
    CardBlockInput,
    CardBlockOutput,
    CustomerMatchInput,
    ToolDefinition,
    get_effective_permitted_states,
)


# Reviewer probe rejections (P1.1)
def test_probe_1_tool_call_rejects_idor_and_bad_idempotency():
    """Probe 1: ToolCall with victim customer_id and short idempotency_key must be rejected."""
    with pytest.raises(ValidationError) as exc_info:
        ToolCall(
            tool="card.block",
            args={"customer_id": "victim"},
            idempotency_key="k",
        )
    err_str = str(exc_info.value)
    has_expected_error = (
        "idempotency_key" in err_str or "customer_id" in err_str or "Invalid arguments" in err_str
    )
    assert has_expected_error


def test_probe_2_tool_call_rejects_unnormalized_tool_names():
    """Probe 2: unnormalized tool names must be rejected (exact match, no normalization)."""
    with pytest.raises(ValidationError) as exc1:
        ToolCall(
            tool="Card.Block",
            args={"card_ref": "card-token-12345678", "reason": "LOST"},
            idempotency_key="idem-uuid-12345678",
        )
    assert "Unknown tool 'Card.Block'" in str(exc1.value)

    with pytest.raises(ValidationError) as exc2:
        ToolCall(
            tool="card.block ",
            args={"card_ref": "card-token-12345678", "reason": "LOST"},
            idempotency_key="idem-uuid-12345678",
        )
    assert "Unknown tool 'card.block '" in str(exc2.value)


def test_probe_3_tool_call_rejects_unregistered_tool():
    """Probe 3: tool='db.query' must be rejected as an uncataloged tool."""
    with pytest.raises(ValidationError) as exc_info:
        ToolCall(
            tool="db.query",
            args={"query": "SELECT * FROM users"},
            idempotency_key="idem-uuid-12345678",
        )
    assert "Unknown tool 'db.query'" in str(exc_info.value)


def test_probe_4_tool_result_rejects_invalid_output_data():
    """Probe 4: ToolResult with invalid pan data must be rejected by output model validation."""
    with pytest.raises(ValidationError) as exc_info:
        ToolResult(
            tool="card.block",
            status=ToolResultStatus.OK,
            data={"pan": "4111111111111111"},
        )
    assert "Invalid output data for tool 'card.block'" in str(exc_info.value)


def test_probe_5_tool_result_rejects_refused_without_reason_code():
    """Probe 5: ToolResult(status='refused') without reason_code must be rejected."""
    with pytest.raises(ValidationError) as exc_info:
        ToolResult(
            tool="card.block",
            status=ToolResultStatus.REFUSED,
            reason_code=None,
        )
    assert "reason_code is required when status is 'refused'" in str(exc_info.value)


# Cycle 2 Reviewer probes (P1 & P2)
def test_tool_result_refused_with_data_payload_is_rejected():
    """Reviewer Probe: ToolResult with status='refused' carrying data must be rejected."""
    with pytest.raises(ValidationError) as exc_info:
        ToolResult(
            tool="card.list",
            status=ToolResultStatus.REFUSED,
            reason_code=ReasonCode.STATE_NOT_ALLOWED,
            data={"pan": "4111111111111111", "holder": "Juan Perez"},
        )
    assert "data must be None when status is 'refused'" in str(exc_info.value)


def test_tool_result_error_with_data_payload_is_rejected():
    """Reviewer Probe: ToolResult with status='error' carrying SQL/dump data must be rejected."""
    with pytest.raises(ValidationError) as exc_info:
        ToolResult(
            tool="account.get_summary",
            status=ToolResultStatus.ERROR,
            reason_code=ReasonCode.INTERNAL_ERROR,
            data={"sql": "select * from customers", "rows": [{"doc": "12345678"}]},
        )
    assert "data must be None when status is 'error'" in str(exc_info.value)


def test_tool_result_envelope_level_receipt_is_rejected():
    """Reviewer Probe: ToolResult does not accept an envelope-level receipt field."""
    receipt = Receipt(
        action="card.block",
        target_masked="**** 1234",
        state_before=ResourceState.ACTIVE,
        state_after=ResourceState.BLOCKED,
        verified_at=datetime.now(timezone.utc),
        audit_id="audit-uuid-12345678",
    )
    with pytest.raises(ValidationError) as exc_info:
        ToolResult(
            tool="kb.search",
            status=ToolResultStatus.REFUSED,
            reason_code=ReasonCode.RATE_LIMITED,
            receipt=receipt,  # type: ignore[call-arg]
        )
    assert "extra_forbidden" in str(exc_info.value) or "receipt" in str(exc_info.value)


def test_tool_result_receipt_action_mismatch_is_rejected():
    """Mismatch probe: card.block result carrying a handoff.create receipt must be rejected."""
    receipt = Receipt(
        action="handoff.create",  # Action mismatch for card.block
        target_masked="ticket_12345678",
        state_before=ResourceState.NONE,
        state_after=ResourceState.QUEUED,
        verified_at=datetime.now(timezone.utc),
        audit_id="audit-uuid-12345678",
    )
    with pytest.raises(ValidationError) as exc_info:
        ToolResult(
            tool="card.block",
            status=ToolResultStatus.OK,
            data={
                "card_ref": "card-token-12345678",
                "status": "BLOCKED",
                "receipt": receipt.model_dump(mode="json"),
            },
        )
    assert "Receipt action 'handoff.create' must match tool name 'card.block'" in str(
        exc_info.value
    )


def test_target_masked_allowlist_validation():
    """Receipt.target_masked enforces allowlist of formats and rejects invalid formats."""
    # Valid allowlist formats
    valid_targets = [
        "**** **** **** 1234",
        "**** 1234",
        "m***@example.com",
        "j***@bank.com",
        "***-***-5678",
        "card_12345678",
        "hnd_12345678",
        "otp_12345678",
        "chal_12345678",
        "ticket_12345678",
    ]
    for target in valid_targets:
        r = Receipt(
            action="card.block",
            target_masked=target,
            state_before=ResourceState.ACTIVE,
            state_after=ResourceState.BLOCKED,
            verified_at=datetime.now(timezone.utc),
            audit_id="audit-uuid-12345678",
        )
        assert r.target_masked == target

    # Invalid formats rejected (specifically '** john.smith@bank.com')
    invalid_targets = [
        "** john.smith@bank.com",
        "john.smith@bank.com",
        "4111111111111234",
        "short",
    ]
    for target in invalid_targets:
        with pytest.raises(ValidationError):
            Receipt(
                action="card.block",
                target_masked=target,
                state_before=ResourceState.ACTIVE,
                state_after=ResourceState.BLOCKED,
                verified_at=datetime.now(timezone.utc),
                audit_id="audit-uuid-12345678",
            )


def test_strict_mode_rejects_string_integer_coercion():
    """Strict mode prevents coercion of string integer like {'limit': '10'}."""
    # Coercion via ToolCall envelope must fail
    with pytest.raises(ValidationError) as exc_info:
        ToolCall(
            tool="transaction.list_recent",
            args={"limit": "10"},
        )
    assert "Invalid arguments for tool 'transaction.list_recent'" in str(exc_info.value)


def test_tool_call_stores_json_dump_of_args():
    """ToolCall.args stores model_dump(mode='json') rather than raw dict."""
    call = ToolCall(
        tool="transaction.list_recent",
        args={"limit": 15},
    )
    assert call.args == {"card_ref": None, "limit": 15}
    assert isinstance(call.args["limit"], int)


# Mutating tools & Idempotency tests (P1.2)
def test_all_mutating_tools_require_idempotency_key():
    """Every tool in MUTATING_TOOLS must reject missing, short, or invalid idempotency keys."""
    expected_mutating = {"card.block", "handoff.create", "otp.send", "otp.verify"}
    assert MUTATING_TOOLS == expected_mutating
    assert WRITE_TOOLS == expected_mutating

    sample_args = {
        "card.block": {"card_ref": "card-token-12345678", "reason": "LOST"},
        "handoff.create": {
            "reason": "SUSPECTED_FRAUD",
            "summary": "Customer confirmed suspicious card charge.",
            "priority": "HIGH",
            "department": "FRAUD_OPERATIONS",
        },
        "otp.send": {},
        "otp.verify": {"code": "123456"},
    }

    for tool_name in expected_mutating:
        args = sample_args[tool_name]

        # Missing idempotency key
        with pytest.raises(ValidationError):
            ToolCall(tool=tool_name, args=args, idempotency_key=None)

        # Too short idempotency key (< 8 chars)
        with pytest.raises(ValidationError):
            ToolCall(tool=tool_name, args=args, idempotency_key="short")

        # Invalid characters
        with pytest.raises(ValidationError):
            ToolCall(tool=tool_name, args=args, idempotency_key="bad key with spaces!")

        # Valid idempotency key succeeds
        call = ToolCall(
            tool=tool_name,
            args=args,
            idempotency_key="valid-idem-key-12345",
        )
        assert call.tool == tool_name
        assert call.idempotency_key == "valid-idem-key-12345"


def test_read_tools_allow_omitted_idempotency_key():
    """Read tools do not require an idempotency_key."""
    for tool_name, args in [
        ("card.list", {}),
        ("customer.match", {"document_type": "NATIONAL_ID", "document_number": "12345678"}),
        ("account.get_summary", {}),
        ("kb.search", {"query": "tarjeta bloqueada"}),
    ]:
        call = ToolCall(
            tool=tool_name,
            version="1.0",
            args=args,
            idempotency_key=None,
        )
        assert call.tool == tool_name
        assert call.idempotency_key is None


def test_verification_states_enum():
    """Verify all verification states from ADR-0003 are defined."""
    expected = {
        "ANONYMOUS",
        "IDENTIFIED",
        "OTP_PENDING",
        "VERIFIED",
        "LOCKED",
        "HANDED_OFF",
    }
    actual = {s.value for s in VerificationState}
    assert actual == expected


# Cycle 3 Reviewer tests: birth_date string + opaque-ref PAN guard
def test_tool_call_customer_match_accepts_iso_birth_date_string():
    """ToolCall with customer.match accepts birth_date as an ISO string."""
    call = ToolCall(
        tool="customer.match",
        args={
            "document_type": "NATIONAL_ID",
            "document_number": "12345678",
            "birth_date": "1990-05-01",
        },
    )
    assert call.tool == "customer.match"
    assert call.args["birth_date"] == "1990-05-01"


def test_customer_match_input_model_validate_json_with_birth_date():
    """CustomerMatchInput.model_validate_json accepts JSON with ISO date string."""
    json_str = (
        '{"document_type": "NATIONAL_ID", "document_number": "12345678", '
        '"birth_date": "1990-05-01"}'
    )
    model = CustomerMatchInput.model_validate_json(json_str)
    assert model.birth_date == date(1990, 5, 1)


def test_customer_match_tool_call_round_trip():
    """ToolCall args can be dumped to JSON-mode dict and re-validated by CustomerMatchInput."""
    call = ToolCall(
        tool="customer.match",
        args={
            "document_type": "NATIONAL_ID",
            "document_number": "12345678",
            "birth_date": "1990-05-01",
        },
    )
    revalidated = CustomerMatchInput.model_validate(call.args)
    assert revalidated.document_number == "12345678"
    assert revalidated.birth_date == date(1990, 5, 1)


def test_strict_int_and_bool_rejections():
    """StrictInt and StrictBool reject string coercion across tool models."""
    with pytest.raises(ValidationError):
        ToolCall(tool="transaction.list_recent", args={"limit": "10"})

    with pytest.raises(ValidationError):
        ToolCall(tool="kb.search", args={"query": "test query", "limit": "5"})

    with pytest.raises(ValidationError):
        ToolCall(tool="account.get_summary", args={"include_balances": "true"})


def test_opaque_ref_pan_guard_rejects_12_or_more_digits():
    """PAN guard: opaque-ref branch rejects >=12 digits even when separated
    by dashes, underscores, or spaces."""
    pan_leak_references = [
        "card_4111111111111111",
        "card-4111111111111111",
        "card_4111-1111-1111-1111",
        "card_4111_1111_1111_1111",
        "hnd_1234-5678-9012",
        "hnd_123456789012",
        "otp_98765432101234",
        "ticket_111122223333",
        "chal_123456789012345",
    ]
    for bad_ref in pan_leak_references:
        with pytest.raises(ValidationError):
            Receipt(
                action="card.block",
                target_masked=bad_ref,
                state_before=ResourceState.ACTIVE,
                state_after=ResourceState.BLOCKED,
                verified_at=datetime.now(timezone.utc),
                audit_id="audit-uuid-12345678",
            )


def test_opaque_ref_pan_guard_accepts_valid_references():
    """Valid opaque references are accepted by Receipt.target_masked."""
    valid_refs = [
        "card_12345678",
        "card-token-12345",
        "hnd_abcdef12",
        "otp_12345678",
        "chal_12345678",
        "ticket_12345678",
    ]
    for good_ref in valid_refs:
        r = Receipt(
            action="card.block",
            target_masked=good_ref,
            state_before=ResourceState.ACTIVE,
            state_after=ResourceState.BLOCKED,
            verified_at=datetime.now(timezone.utc),
            audit_id="audit-uuid-12345678",
        )
        assert r.target_masked == good_ref


# Task 1C-matrix tests: CODE_FLOOR & otp.send server-side channel
def test_every_catalog_entry_subset_of_code_floor():
    """Assert every catalog entry's permitted_states is a subset of CODE_FLOOR[tool]."""
    for tool_name, definition in TOOL_CATALOG.items():
        assert tool_name in CODE_FLOOR, f"Tool '{tool_name}' missing from CODE_FLOOR"
        floor = CODE_FLOOR[tool_name]
        assert definition.permitted_states.issubset(floor), (
            f"Tool '{tool_name}' permitted_states {definition.permitted_states} "
            f"not subset of CODE_FLOOR {floor}"
        )


def test_code_floor_architectural_invariants():
    """Customer-data reads and card.block in VERIFIED; LOCKED/HANDED_OFF in handoff/kb."""
    sensitive_tools = [
        "card.list",
        "transaction.list_recent",
        "account.get_summary",
        "card.block",
    ]
    for tool_name in sensitive_tools:
        assert CODE_FLOOR[tool_name] == frozenset({VerificationState.VERIFIED})

    for tool_name, states in CODE_FLOOR.items():
        if VerificationState.LOCKED in states:
            assert tool_name in {"handoff.create", "kb.search"}
        if VerificationState.HANDED_OFF in states:
            assert tool_name in {"handoff.create", "kb.search"}


def test_no_config_widening_expressible_through_catalog_helpers():
    """Configuration can only RESTRICT the seed matrix/code floor, NEVER widen it."""
    # 1. Attempting to widen card.block to IDENTIFIED raises ValueError
    with pytest.raises(ValueError, match="cannot widen"):
        get_effective_permitted_states("card.block", {VerificationState.IDENTIFIED})

    # 2. Attempting to widen card.list to ANONYMOUS raises ValueError
    with pytest.raises(ValueError, match="cannot widen"):
        get_effective_permitted_states("card.list", {VerificationState.ANONYMOUS})

    # 3. Attempting to widen account.get_summary to LOCKED raises ValueError
    with pytest.raises(ValueError, match="cannot widen"):
        get_effective_permitted_states("account.get_summary", {VerificationState.LOCKED})

    # 4. Attempting to instantiate ToolDefinition with widened states raises ValueError
    with pytest.raises(ValueError, match="exceeds CODE_FLOOR"):
        ToolDefinition(
            name="card.block",
            description="Widened card block",
            input_model=CardBlockInput,
            output_model=CardBlockOutput,
            mutates_state=True,
            permitted_states=frozenset({VerificationState.ANONYMOUS}),
        )

    # 5. Valid restrictions succeed
    assert get_effective_permitted_states("card.block", set()) == frozenset()
    assert get_effective_permitted_states(
        "customer.match", {VerificationState.ANONYMOUS}
    ) == frozenset({VerificationState.ANONYMOUS})

    # 6. Attempting to instantiate ToolDefinition missing from CODE_FLOOR fails closed
    with pytest.raises(ValueError, match="missing from CODE_FLOOR"):
        ToolDefinition(
            name="unregistered.custom_tool",
            description="Custom uncataloged tool",
            input_model=CardBlockInput,
            output_model=CardBlockOutput,
            mutates_state=False,
            permitted_states=frozenset({VerificationState.VERIFIED}),
        )


def test_tool_call_otp_send_without_channel():
    """otp.send tool call accepts empty dict; rejects any channel or destination parameter."""
    # Empty args succeeds with idempotency key
    call = ToolCall(
        tool="otp.send",
        args={},
        idempotency_key="idem-valid-12345",
    )
    assert call.tool == "otp.send"
    assert call.args == {}

    # Reject channel argument
    with pytest.raises(ValidationError):
        ToolCall(
            tool="otp.send",
            args={"channel": "EMAIL"},
            idempotency_key="idem-valid-12345",
        )

    # Reject destination argument
    with pytest.raises(ValidationError):
        ToolCall(
            tool="otp.send",
            args={"destination": "user@example.com"},
            idempotency_key="idem-valid-12345",
        )
