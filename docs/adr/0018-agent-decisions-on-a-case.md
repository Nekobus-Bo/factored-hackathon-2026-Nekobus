# ADR-0018: agents close or escalate a case, and see the customer's feedback

**Status:** Accepted · **Date:** 2026-10-02 · **Deciders:** TODO (team)

## Context

The back-office review of 2026-10-02 asked for quick actions on a case: approve, reject or escalate, from the queue or from the case page. Today a claim moves a handoff to `ASSIGNED` and nothing moves it further ([ADR-0013](0013-front-ends-bff-takeover.md), [limitations](../limitations.md) "Claim without release or close"). A wrong claim is repaired in the database, assigned cases stay in the queue forever, and there is no resolution number.

The same review asked for the customer's answer to "¿Te ayudó el asistente?" ([ADR-0017](0017-assistant-feedback-after-handoff.md)) to reach the agent and the metrics page. banking-core stores it and shows it nowhere.

The decision is the agent's. The assistant never resolves a dispute ([ADR-0003](0003-deterministic-vs-ai.md)), and nothing in this change lets the model propose an outcome.

## Decision

**banking-core records two new decisions on a handoff, close and escalate, audited and re-read. The back office calls them from the queue summary and the case page, and sends the customer a fixed closing message.**

- **Close.** `POST /v1/admin/handoffs/{ref}/close` with `{agent_ref, outcome, reason}` moves the handoff to a new status `CLOSED` and stores `outcome` (`APPROVED`, `REJECTED` or `RESOLVED`), the reject reason, who closed it and when. The audit row (`admin.handoff.closed`, actor `agent`) and the change commit together, with the audit lock taken before the row lock, as the claim does.
- **Escalate.** `POST /v1/admin/handoffs/{ref}/escalate` with `{agent_ref, department, raise_to_urgent}` puts the handoff back in the queue (`QUEUED`, no agent) in another department, and can raise its priority to `URGENT`, never lower it. Audited as `admin.handoff.escalated`, with the departments and priorities before and after.
- **Who may decide.** The handoff must be `QUEUED`, or `ASSIGNED` to the same agent. Deciding on a queued case claims it in the same transaction. A case another agent holds is a 409 `claimed_by_another_agent`, as the claim answers today. A closed case is a 409 `already_closed`, except that the same close by the same agent returns the stored row with no second write (a retried request).
- **What each outcome means comes from configuration, not from the browser.** `banking_core/handoff/decisions.json` maps each handoff reason to its outcomes, its reject reasons and its closing messages in es, pt and en. Disputes and unrecognized charges: approve or reject the claim. Suspected fraud: confirm or reject. A locked customer or a failed verification: restore access or keep it locked. A customer request: one outcome, `RESOLVED`. Approving needs the customer verified when the handoff was created. banking-core enforces every rule and lists, in the handoff detail, the outcomes and reasons a case allows, so the screen offers only what the server will accept. The reject reasons are a closed enum in the contracts; the file chooses which apply to each reason.
- **Nothing moves money or unlocks anything.** A close records the agent's decision. A refund, a chargeback or an unlock would each be a banking operation with its own tool and contract, and none exists.
- **The customer gets a fixed message.** After a close, the back-office BFF takes the conversation over for the agent (idempotent, as in the claim) and sends the configured closing message in the conversation's language through the existing agent message route, with `client_message_id = close_<handoff_ref>` so a retry cannot send it twice. If the conversation has expired, the case still closes and the answer says the customer was not notified.
- **Escalating releases the conversation.** A new agent API route, `POST /v1/agent/conversations/{id}/release`, frees a conversation its holder took over. The assistant stays off (the takeover stays active, with no agent), and the next agent's takeover succeeds. This amends ADR-0013's "no release, no transfer". "No hand-back to the assistant" still holds.
- **Feedback reaches the back office.** The handoff detail carries `feedback: {helpful, recorded_at} | null`. The metrics carry the yes and no counts for handoffs created in the window, the recent "no" cases, the current queue (waiting, urgent, oldest) and the same summary numbers for the window before, so the page can show a change.
- **The queue row shows the disputed amount.** The list carries `disputed_amount: {amount_minor, currency} | null`, read from the summary `handoff.create` stored. No new query, no PII.

## Options considered

| Option | Why not |
|---|---|
| Outcomes and reasons in the front end | The browser would decide what a case allows. banking-core must enforce it anyway, so the rule would live twice |
| A free-text note on escalation or rejection | Free text typed by an agent is PII-prone and goes into the audit chain; a closed list does not |
| Close by deleting the claim or with `PENDING` | `PENDING` already means something to `handoff.create`, and a closed case must stay readable with its outcome |
| Send the closing message from banking-core | banking-core cannot write to a conversation; the orchestrator owns it, and the BFF already holds the agent token |
| A new engine-built "case closed" block in the customer chat | Needs the orchestrator, the customer app and an eval scenario. The fixed message reuses a route that exists |
| Compare against the previous window in the browser | Two metrics calls with overlapping windows; one call with both is simpler and atomic |

## Consequences

- One migration (`0010_handoff_decisions`): the status constraint gains `CLOSED`, and `ops.handoff` gains `outcome`, `outcome_reason`, `closed_by` and `closed_at`. Downgrading drops them; the audit rows stay.
- `HandoffStatus` gains `CLOSED` in the contracts (Python, JSON Schemas, Zod). An open handoff, for `handoff.create`'s "one open handoff per session", is any status but `CLOSED`.
- Two banking-core routes, one orchestrator route and two BFF routes. The closing messages live in banking-core's configuration file, edited by pull request.
- The metrics page can show resolutions for the first time: `CLOSED` is counted by status like the others.
- Still not built: reopening a closed case, unclaiming without escalating, per-language metrics for feedback (a handoff stores no language), and feedback when the assistant solves a case alone (ADR-0017).
