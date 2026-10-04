// Payloads shaped like the orchestrator's answers. The block fixtures satisfy the contracts' schemas
// (tests/fixtures.test.ts parses them), so a drift in the contract breaks a test here first.

import type { TurnTrace } from "@pattern-blue/contracts";

export const CONVERSATION_ID = "conv_0123456789abcdef0123456789abcdef";
export const CLIENT_MESSAGE_ID = "msg_0123456789abcdef";

export const TEXT_BLOCK = { type: "text", text: "Hola, puedo ayudarte con tu tarjeta." };

export const CARD_BLOCK_RECEIPT = {
  type: "receipt",
  receipt: {
    action: "card.block",
    target_masked: "**** **** **** 4821",
    state_before: "ACTIVE",
    state_after: "BLOCKED",
    verified_at: "2026-09-29T15:42:18Z",
    audit_id: "aud_20481abc",
  },
};

export const OTP_SEND_RECEIPT = {
  type: "receipt",
  receipt: {
    action: "otp.send",
    target_masked: "d***@example.com",
    state_before: "IDENTIFIED",
    state_after: "OTP_PENDING",
    verified_at: "2026-09-29T15:40:02Z",
    audit_id: "aud_20479abc",
  },
};

export const OTP_VERIFY_RECEIPT = {
  type: "receipt",
  receipt: {
    action: "otp.verify",
    target_masked: "chal_abcdef123456",
    state_before: "OTP_PENDING",
    state_after: "VERIFIED",
    verified_at: "2026-09-29T15:41:11Z",
    audit_id: "aud_20480abc",
  },
};

/** The summary carries facts the customer view must never show: the test greps for these strings. */
export const SECRET_FACT = "internal-fact-do-not-show";
export const SECRET_ACTION = "internal-action-do-not-show";
export const SECRET_QUESTION = "internal-question-do-not-show";

export const HANDOFF_BLOCK = {
  type: "handoff",
  handoff_id: "hnd_abcd1234efgh",
  status: "QUEUED",
  department: "DISPUTES",
  priority: "URGENT",
  queue_position: 2,
  summary: {
    verified_facts: { verification_state: "VERIFIED", note: SECRET_FACT },
    actions_taken: [SECRET_ACTION, { tool: "card.block", status: "ok" }],
    verification_method: "otp_email",
    open_questions: [{ source: "model_unverified", text: SECRET_QUESTION }],
  },
  receipt: {
    action: "handoff.create",
    target_masked: "hnd_abcd1234efgh",
    state_before: "NONE",
    state_after: "QUEUED",
    verified_at: "2026-09-29T15:43:00Z",
    audit_id: "aud_handoff-secret-audit",
  },
};

export const UNKNOWN_BLOCK = { type: "carousel", items: ["a", "b"] };

export const CREATE_RESPONSE = { conversation_id: CONVERSATION_ID, language: "es" as const };

export const SEND_RESPONSE = { conversation_id: CONVERSATION_ID, blocks: [TEXT_BLOCK] };

export const FEEDBACK_RESPONSE = { helpful: true, recorded_at: "2026-09-29T15:50:00Z" };

export const TRANSCRIPT = {
  conversation_id: CONVERSATION_ID,
  language: "es",
  messages: [
    { role: "user", content: "Perdí mi tarjeta", blocks: [], created_at: "2026-09-29T15:39:00Z" },
    { role: "assistant", content: "Lo siento.", blocks: [], created_at: "2026-09-29T15:39:03Z" },
  ],
  takeover: { active: false, since: null },
};

export const INBOX_CODE = "482916";

export function inboxResponse(expiresAt: string, receivedAt = "2026-09-29T15:40:02Z") {
  return {
    messages: [
      {
        channel: "email",
        destination_masked: "d***@example.com",
        code: INBOX_CODE,
        received_at: receivedAt,
        expires_at: expiresAt,
      },
    ],
  };
}

/** A detective-mode trace (ADR-0019): what a turn returns while the mode is on. */
export const TRACE: TurnTrace = {
  trace_version: "1",
  turn_id: "turn_test0001",
  prompt_version: "p1",
  total_ms: 812.4,
  tool_rounds: 0,
  events: [
    {
      seq: 0,
      kind: "masking",
      label: "masking",
      start_ms: 0.4,
      duration_ms: 1.2,
      status: "ok",
      note: null,
      encoder: null,
      masking: {
        masked_text: "perdí mi tarjeta, soy [DOC_1]",
        placeholders: ["[DOC_1]"],
        regex_only: false,
        encoder_spans_added: 0,
        otp_pending: false,
        failed: false,
      },
      decisions: null,
      llm_call: null,
      tool_call: null,
      blocks: null,
    },
  ],
};

/** A turn where the model asked for a tool the engine refused before banking-core: an LLM call, then the tool. */
export const TRACE_TOOL: TurnTrace = {
  trace_version: "1",
  turn_id: "turn_test0002",
  prompt_version: "p1",
  total_ms: 2400,
  tool_rounds: 1,
  events: [
    {
      seq: 0,
      kind: "llm_call",
      label: "llm #1",
      start_ms: 10,
      duration_ms: 1900,
      status: "ok",
      note: null,
      encoder: null,
      masking: null,
      decisions: null,
      llm_call: {
        round: 1,
        model: "openai/test-model",
        prompt_version: "p1",
        cached: false,
        recording_key: null,
        tools_offered: ["customer_match", "otp_send"],
        messages_from: 0,
        messages: [
          { role: "system", content: "You are the assistant.", tool_calls: null, tool_call_id: null },
          { role: "user", content: "soy [DOC_1]", tool_calls: null, tool_call_id: null },
        ],
        response_content: null,
        response_tool_calls: [{ call_id: "call_1", name: "customer_match", arguments: '{"document_number":"[DOC_1]"}' }],
        prompt_tokens: 2500,
        completion_tokens: 30,
        total_tokens: 2530,
        cost_usd: 0.00034,
      },
      tool_call: null,
      blocks: null,
    },
    {
      seq: 1,
      kind: "tool_call",
      label: "customer.match",
      start_ms: 1915,
      duration_ms: 0.4,
      status: "error",
      note: null,
      encoder: null,
      masking: null,
      decisions: null,
      llm_call: null,
      tool_call: {
        call_id: "call_1",
        llm_name: "customer_match",
        tool: "customer.match",
        arguments: '{"document_number":"[DOC_1]"}',
        executed: false,
        local_reason: "refused by the engine before banking-core (INVALID_ARGUMENTS)",
        status: "error",
        reason_code: "INVALID_ARGUMENTS",
        flow_state: null,
        flow_next: [],
        flow_allowed: [],
        feedback: '{"reason_code":"INVALID_ARGUMENTS","status":"error"}',
      },
      blocks: null,
    },
  ],
};

export const SEND_RESPONSE_TRACED = { ...SEND_RESPONSE, trace: TRACE };
