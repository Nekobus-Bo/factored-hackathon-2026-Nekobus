# HandoffCard

The case file a human agent receives: priority, department, language, the facts `banking-core` verified, the actions already taken and the questions still open.

## Consumer provides

A handoff record: `caseId`, `priority` (URGENT, HIGH, NORMAL), `department` (FRAUD_OPERATIONS, DISPUTES, CUSTOMER_SUPPORT), `language` (es, pt, en), masked customer, wait time, `verifiedFacts` (each from a tool receipt), `actions` (tool, outcome, receipt), `openQuestions`. The model may propose the open questions; it never adds a fact.

## Parts

| Class | Notes |
| --- | --- |
| `pb-card pb-handoff` | Card with extra top padding for the stripe. |
| `pb-hazard` (first child) | URGENT only. Not for HIGH or NORMAL. |
| `pb-handoff__head` | `pb-caseid` link (stencil), priority chip, `HANDED_OFF` chip. |
| `pb-handoff__meta` | `pb-tag` department, `pb-tag` language, masked customer and wait in `small`. |
| `pb-handoff__sec` with `h3` | Sections: Hechos verificados (`pb-kv`), Acciones tomadas (`pb-steps`), Preguntas abiertas (`pb-questions`, stencil numerals in `violet`). |
| `pb-handoff__actions` | `pb-btn--sm`: Tomar caso (primary), Reasignar (secondary). |

## Rules

- Facts are only what a tool returned with a receipt. A statement the customer made but nothing verified belongs under open questions, phrased as a question.
- The card never proposes a resolution. Disputes are resolved by people; keep the closing line "El asistente no resuelve disputas."
- Mask everything: `D*** M***`, `•••• 4821`. The unmasked identity is fetched by the agent's own authorized tool, never embedded here.
- Verification method is always named (OTP (email)) with its time.
- Compact form (no stripe, facts and actions only) is fine for NORMAL cases.
