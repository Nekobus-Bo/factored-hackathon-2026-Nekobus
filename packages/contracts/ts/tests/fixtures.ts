// Payloads shaped like the real ones. The block fixtures are the ones packages/contracts/tests/test_blocks.py
// validates on the Python side; the API fixtures follow the front-end spec's HTTP contract.

export const CONVERSATION_ID = "conv_0123456789abcdef0123456789abcdef";
export const OTHER_CONVERSATION_ID = "conv_fedcba9876543210fedcba9876543210";
export const SESSION_REF = "sess_0123456789abcdef0123456789abcdef";
export const HANDOFF_REF = "hnd_abcdefghijklmnop";
export const AGENT_REF = "agente@patternblue.example";
export const NOW = "2026-09-29T12:00:00Z";
export const LATER = "2026-09-29T12:05:30.123456Z";

export const RECEIPT = {
  action: "card.block",
  target_masked: "card_ab12cd34",
  state_before: "ACTIVE",
  state_after: "BLOCKED",
  verified_at: "2026-09-27T12:00:00Z",
  audit_id: "aud_0001abcd",
};

export const HANDOFF_RECEIPT = {
  ...RECEIPT,
  action: "handoff.create",
  target_masked: "hnd_abcd1234",
  state_before: "NONE",
  state_after: "QUEUED",
};

export const SUMMARY = {
  verified_facts: {
    verification_state: "VERIFIED",
    customer_identified: true,
    policy_flags: [] as string[],
    disputed_transaction: { amount_minor: 125000, currency: "COP", merchant: "ACME" },
  },
  actions_taken: ["card.block", { tool: "otp.verify", status: "ok" }],
  verification_method: "document_match_and_otp",
  open_questions: [{ source: "model_unverified", text: "Stored question." }],
};

export const TEXT_BLOCK = { type: "text", text: "hola" };
export const RECEIPT_BLOCK = { type: "receipt", receipt: RECEIPT };
export const HANDOFF_BLOCK = {
  type: "handoff",
  handoff_id: "hnd_abcd1234",
  status: "QUEUED",
  department: "DISPUTES",
  priority: "HIGH",
  queue_position: 4,
  summary: SUMMARY,
  receipt: HANDOFF_RECEIPT,
};

export const HANDOFF_ITEM = {
  handoff_ref: HANDOFF_REF,
  status: "QUEUED",
  priority: "URGENT",
  department: "FRAUD_OPERATIONS",
  reason: "SUSPECTED_FRAUD",
  created_at: NOW,
  queue_position: 1,
  assigned_agent: null,
  assigned_at: null,
  session_ref: SESSION_REF,
};

export const HANDOFF_DETAIL = { ...HANDOFF_ITEM, summary: SUMMARY };

export const CLAIMED_DETAIL = {
  ...HANDOFF_DETAIL,
  status: "ASSIGNED",
  queue_position: null,
  assigned_agent: AGENT_REF,
  assigned_at: LATER,
};

export const TAKEOVER_RESPONSE = {
  conversation_id: CONVERSATION_ID,
  takeover: { active: true, since: LATER, agent_ref: AGENT_REF },
};

export const METRICS = {
  generated_at: NOW,
  window_hours: 24,
  tool_calls: [
    { action: "card.block", decision: "allowed", reason_code: null, count: 7 },
    { action: "card.block", decision: "refused", reason_code: "STATE_NOT_ALLOWED", count: 2 },
    { action: "otp.verify", decision: "error", reason_code: "INTERNAL_ERROR", count: 1 },
  ],
  handoffs: {
    total: 9,
    by_status: { QUEUED: 6, ASSIGNED: 3 },
    by_priority: { URGENT: 2, HIGH: 3, NORMAL: 4 },
    by_department: { FRAUD_OPERATIONS: 5, DISPUTES: 4 },
  },
  cards_blocked: 7,
  otp: { sent: 12, verified: 9, failed: 3 },
};

export const POLICY_CONFIG = { amount_mode: "flag", thresholds_minor: { COP: 500000000, USD: 100000 }, version: 3 };

export const TOOL_POLICY = {
  version: 2,
  tools: { "card.block": ["VERIFIED"], "handoff.create": [] as string[], "kb.search": ["ANONYMOUS", "VERIFIED"] },
  disabled: ["handoff.create"],
  code_floor: { "card.block": ["VERIFIED"], "handoff.create": ["ANONYMOUS", "VERIFIED", "LOCKED"] },
};

export const DEMO_RESET = {
  cards_reset: 6,
  cards_changed: 2,
  cards_missing: 0,
  attempt_limits_cleared: 4,
  tool_policy_version: 5,
  tool_policy_changed: true,
};
