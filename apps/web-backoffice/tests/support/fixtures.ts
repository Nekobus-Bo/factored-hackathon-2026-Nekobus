// Contract-shaped data for the tests and for the visual check. Every value here passes the schemas of
// @pattern-blue/contracts (tests/fixtures.test.ts checks it), and none of it is real: the ids are made up,
// the customer is masked, the amounts are the demo's.

import type {
  AgentMessageResponse,
  AgentTranscriptResponse,
  BackofficeHandoffDetail,
  DemoResetResponse,
  HandoffDetail,
  HandoffItem,
  MetricsResponse,
  PolicyConfigResponse,
  TakeoverResponse,
  ToolPolicyResponse,
} from "@pattern-blue/contracts";

export const AGENT_EMAIL = "agent@demo.local";
export const CONVERSATION_ID = "conv_0123456789abcdef0123456789abcdef";
export const SESSION_REF = "sess_0123456789abcdef0123456789abcdef";

const isoAgo = (seconds: number, now = Date.now()) => new Date(now - seconds * 1000).toISOString();

export function handoffItems(now = Date.now()): HandoffItem[] {
  return [
    {
      handoff_ref: "hnd_qwertyuiopasdfgh",
      status: "QUEUED",
      priority: "URGENT",
      department: "FRAUD_OPERATIONS",
      reason: "SUSPECTED_FRAUD",
      created_at: isoAgo(462, now),
      queue_position: 1,
      assigned_agent: null,
      assigned_at: null,
      session_ref: SESSION_REF,
    },
    {
      handoff_ref: "hnd_zxcvbnmasdfghjkl",
      status: "QUEUED",
      priority: "HIGH",
      department: "DISPUTES",
      reason: "DISPUTE_CLAIM",
      created_at: isoAgo(725, now),
      queue_position: 2,
      assigned_agent: null,
      assigned_at: null,
      session_ref: "sess_fedcba9876543210fedcba9876543210",
    },
    {
      handoff_ref: "hnd_poiuytrewqlkjhgf",
      status: "ASSIGNED",
      priority: "NORMAL",
      department: "CUSTOMER_SUPPORT",
      reason: "CUSTOMER_REQUEST",
      created_at: isoAgo(1830, now),
      queue_position: null,
      assigned_agent: "marta@demo.local",
      assigned_at: isoAgo(1500, now),
      session_ref: "sess_00112233445566778899aabbccddeeff",
    },
    {
      handoff_ref: "hnd_mnbvcxzlkjhgfdsa",
      status: "QUEUED",
      priority: "NORMAL",
      department: "CUSTOMER_SUPPORT",
      reason: "VERIFICATION_FAILED",
      created_at: isoAgo(198, now),
      queue_position: 3,
      assigned_agent: null,
      assigned_at: null,
      session_ref: "sess_aabbccddeeff00112233445566778899",
    },
  ];
}

export function handoffDetail(overrides: Partial<HandoffDetail> = {}, now = Date.now()): HandoffDetail {
  const item = handoffItems(now)[0] as HandoffItem;
  return {
    ...item,
    summary: {
      verified_facts: {
        verification_state: "VERIFIED",
        customer_identified: true,
        policy_flags: ["HANDOFF_REQUIRED", "PRIORITY"],
        disputed_transaction: {
          transaction_id: "txn_4f2a91",
          amount_minor: 13999,
          currency: "USD",
          merchant: "Global Electronics Megastore",
          posted_at: "2026-09-27T14:03:11+00:00",
          card_masked: "**** **** **** 4821",
        },
      },
      actions_taken: [
        { action: "customer.match", decision: "allowed", reason_code: null, audit_id: "aud_00020477" },
        { action: "otp.send", decision: "allowed", reason_code: null, audit_id: "aud_00020479" },
        { action: "otp.verify", decision: "allowed", reason_code: null, audit_id: "aud_00020480" },
        { action: "card.block", decision: "allowed", reason_code: null, audit_id: "aud_00020481" },
        { action: "account.get_summary", decision: "refused", reason_code: "STATE_NOT_ALLOWED", audit_id: "aud_00020482" },
      ],
      verification_method: "document_match_and_otp",
      open_questions: [
        { source: "model_unverified", text: "The customer says they do not recognize the USD 139.99 charge and asks for a replacement card." },
      ],
    },
    ...overrides,
  };
}

export function backofficeDetail(overrides: Partial<BackofficeHandoffDetail> = {}, now = Date.now()): BackofficeHandoffDetail {
  return { ...handoffDetail({}, now), conversation_id: CONVERSATION_ID, ...overrides };
}

export function claimedDetail(agentRef = AGENT_EMAIL, now = Date.now()): HandoffDetail {
  return handoffDetail({ status: "ASSIGNED", queue_position: null, assigned_agent: agentRef, assigned_at: isoAgo(2, now) }, now);
}

export function takeoverResponse(agentRef = AGENT_EMAIL, now = Date.now()): TakeoverResponse {
  return { conversation_id: CONVERSATION_ID, takeover: { active: true, since: isoAgo(2, now), agent_ref: agentRef } };
}

export function transcript(
  options: { takeover?: AgentTranscriptResponse["takeover"]; withAgentMessage?: boolean } = {},
  now = Date.now(),
): AgentTranscriptResponse {
  const messages: AgentTranscriptResponse["messages"] = [
    { role: "user", content: "Hola, no reconozco un cargo de USD 139.99 en mi tarjeta.", blocks: [], created_at: isoAgo(900, now) },
    {
      role: "assistant",
      content: "Puedo ayudarte. Primero necesito confirmar tu identidad. Te envié un código a [EMAIL_1].",
      blocks: [],
      created_at: isoAgo(880, now),
    },
    { role: "user", content: "Mi código es [OTP_1]", blocks: [], created_at: isoAgo(840, now) },
    {
      role: "assistant",
      content: "Bloqueé la tarjeta y pasé tu caso a un agente de Operaciones de fraude.",
      blocks: [
        {
          type: "receipt",
          receipt: {
            action: "card.block",
            target_masked: "****4821",
            state_before: "ACTIVE",
            state_after: "BLOCKED",
            verified_at: isoAgo(830, now),
            audit_id: "aud_00020481",
          },
        },
      ],
      created_at: isoAgo(830, now),
    },
  ];
  if (options.withAgentMessage) {
    messages.push({ role: "agent", content: "Hola, soy [NAME_1], del equipo de fraude. Ya revisé tu caso.", blocks: [], created_at: isoAgo(20, now) });
  }
  return {
    conversation_id: CONVERSATION_ID,
    language: "es",
    messages,
    takeover: options.takeover ?? { active: false, since: null, agent_ref: null },
  };
}

export function agentMessageResponse(text: string, now = Date.now()): AgentMessageResponse {
  return { message: { role: "agent", content: text, blocks: [], created_at: new Date(now).toISOString() } };
}

export function policyConfig(): PolicyConfigResponse {
  return { amount_mode: "block", thresholds_minor: { USD: 10000, COP: 200000000, BRL: 250000, EUR: 50000 }, version: 7 };
}

export function toolPolicy(): ToolPolicyResponse {
  return {
    version: 4,
    tools: {
      "account.get_summary": [],
      "card.block": ["VERIFIED"],
      "card.list": ["VERIFIED"],
      "customer.match": ["ANONYMOUS", "IDENTIFIED"],
      "handoff.create": ["ANONYMOUS", "IDENTIFIED", "OTP_PENDING", "VERIFIED", "LOCKED", "HANDED_OFF"],
      "identity.verify_document": ["IDENTIFIED"],
      "kb.search": ["ANONYMOUS", "IDENTIFIED", "OTP_PENDING", "VERIFIED", "LOCKED", "HANDED_OFF"],
      "otp.send": ["IDENTIFIED", "OTP_PENDING"],
      "otp.verify": ["OTP_PENDING"],
      "transaction.list_recent": ["VERIFIED"],
    },
    disabled: ["account.get_summary"],
    code_floor: {
      "account.get_summary": ["VERIFIED"],
      "card.block": ["VERIFIED"],
      "card.list": ["VERIFIED"],
      "customer.match": ["ANONYMOUS", "IDENTIFIED"],
      "handoff.create": ["ANONYMOUS", "HANDED_OFF", "IDENTIFIED", "LOCKED", "OTP_PENDING", "VERIFIED"],
      "identity.verify_document": ["IDENTIFIED"],
      "kb.search": ["ANONYMOUS", "HANDED_OFF", "IDENTIFIED", "LOCKED", "OTP_PENDING", "VERIFIED"],
      "otp.send": ["IDENTIFIED", "OTP_PENDING"],
      "otp.verify": ["OTP_PENDING"],
      "transaction.list_recent": ["VERIFIED"],
    },
  };
}

export function metrics(hours = 24, now = Date.now()): MetricsResponse {
  return {
    generated_at: new Date(now).toISOString(),
    window_hours: hours,
    tool_calls: [
      { action: "customer.match", decision: "allowed", reason_code: null, count: 42 },
      { action: "customer.match", decision: "refused", reason_code: "NOT_MATCHED", count: 5 },
      { action: "otp.send", decision: "allowed", reason_code: null, count: 37 },
      { action: "otp.verify", decision: "allowed", reason_code: null, count: 31 },
      { action: "otp.verify", decision: "refused", reason_code: "INVALID_ARGUMENTS", count: 4 },
      { action: "card.block", decision: "allowed", reason_code: null, count: 26 },
      { action: "handoff.create", decision: "allowed", reason_code: null, count: 9 },
      { action: "account.get_summary", decision: "refused", reason_code: "STATE_NOT_ALLOWED", count: 3 },
      { action: "card.block", decision: "error", reason_code: "INTERNAL_ERROR", count: 1 },
    ],
    handoffs: {
      total: 9,
      by_status: { QUEUED: 4, ASSIGNED: 5 },
      by_priority: { URGENT: 2, HIGH: 3, NORMAL: 4 },
      by_department: { FRAUD_OPERATIONS: 3, DISPUTES: 3, CUSTOMER_SUPPORT: 3 },
    },
    cards_blocked: 26,
    otp: { sent: 37, verified: 31, failed: 4 },
  };
}

export function demoReset(): DemoResetResponse {
  return {
    cards_reset: 12,
    cards_changed: 3,
    cards_missing: 0,
    attempt_limits_cleared: 5,
    tool_policy_version: 5,
    tool_policy_changed: true,
  };
}
