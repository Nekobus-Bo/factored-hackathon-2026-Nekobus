// The flows screen: how a session moves through the verification state machine, which tools the policy in
// force allows in each state, and the assistant's main flows end to end. Read only; it draws what
// banking-core enforces (ADR-0003, ADR-0016) and links to Guardrails for changes. The diagrams are plain
// lists styled with the tokens, so they wrap on a phone and read in order with a screen reader.

import type { ToolPolicyResponse, VerificationState } from "@pattern-blue/contracts";
import { useMachine } from "@xstate/react";
import type { ReactNode } from "react";
import type { MessageKey } from "../i18n";
import { flowsMachine } from "../machines/flows";
import { useAppServices, useI18n } from "./context";
import { Alert, chipState, Icon, StateChip } from "./ui";

/**
 * What the system sets in the data type inside a sentence: a tool (`customer.match`), a code (`SUSPECTED_FRAUD`) and a
 * snake_case name (`confirm_gate`). The dictionaries stay plain strings; the screen wraps these tokens when it draws them.
 */
const IDENTIFIER = /\b[a-z]+(?:\.[a-z_]+)+\b|\b[A-Z]{2,}(?:_[A-Z]+)+\b|\b[a-z]+(?:_[a-z]+)+\b/g;

export function Identifiers({ text }: { text: string }) {
  const parts: ReactNode[] = [];
  let from = 0;
  for (const match of text.matchAll(IDENTIFIER)) {
    if (match.index > from) parts.push(text.slice(from, match.index));
    parts.push(
      <code key={match.index} className="pb-t-mono">
        {match[0]}
      </code>,
    );
    from = match.index + match[0].length;
  }
  if (from < text.length) parts.push(text.slice(from));
  return <>{parts}</>;
}

export const STATES: readonly VerificationState[] = ["ANONYMOUS", "IDENTIFIED", "OTP_PENDING", "VERIFIED", "LOCKED", "HANDED_OFF"];

/** The forward path to VERIFIED: each state and the tool that leaves it (contracts VERIFICATION_PATH). */
const PATH: readonly { state: VerificationState; tool?: string }[] = [
  { state: "ANONYMOUS", tool: "customer.match" },
  { state: "IDENTIFIED", tool: "otp.send" },
  { state: "OTP_PENDING", tool: "otp.verify" },
  { state: "VERIFIED" },
];

/**
 * What an outcome is, in a word and a glyph (never a colour alone). Handoff is routing, not danger: a
 * handoff to Fraude is a handoff. Urgent is only for an outcome whose text itself says it is urgent.
 */
type OutcomeKind = "auto" | "handoff" | "urgent" | "info";

const OUTCOME_CHIP: Record<OutcomeKind, { attr: { "data-state": string } | { "data-tone": string }; icon: string; word: MessageKey }> = {
  auto: { attr: { "data-tone": "success" }, icon: "check", word: "flows.outcomeKind.auto" },
  handoff: { attr: { "data-state": "handed-off" }, icon: "handoff", word: "flows.outcomeKind.handoff" },
  urgent: { attr: { "data-tone": "danger" }, icon: "chev2", word: "flows.outcomeKind.urgent" },
  info: { attr: { "data-tone": "neutral" }, icon: "info", word: "flows.outcomeKind.info" },
};

interface Step {
  title: MessageKey;
  /** The tool, or a quote of the customer for the opening step. */
  tool?: string;
  quote?: MessageKey;
  state?: VerificationState;
}

interface Flow {
  id: "unrecognized" | "fraud" | "lost" | "balance";
  title: MessageKey;
  lede: MessageKey;
  steps: Step[];
  outcomes: { text: MessageKey; kind: OutcomeKind }[];
  notes: { text: MessageKey; pending?: boolean }[];
  example?: ({ who: "customer" | "assistant" | "trace"; text: MessageKey } | { who: "trace"; raw: string })[];
}

const IDENTIFY: Step = { title: "flows.step.identify", tool: "customer.match", state: "IDENTIFIED" };
const VERIFY: Step = { title: "flows.step.verify", tool: "otp.send → otp.verify", state: "OTP_PENDING" };

export const FLOWS: readonly Flow[] = [
  {
    id: "unrecognized",
    title: "flows.unrecognized.title",
    lede: "flows.unrecognized.lede",
    steps: [
      { title: "flows.step.report", quote: "flows.unrecognized.report" },
      IDENTIFY,
      VERIFY,
      { title: "flows.step.findCharge", tool: "transaction.list_recent", state: "VERIFIED" },
      { title: "flows.step.block", tool: "card.block", state: "VERIFIED" },
    ],
    outcomes: [
      { text: "flows.unrecognized.out.auto", kind: "auto" },
      { text: "flows.unrecognized.out.handoff", kind: "handoff" },
      { text: "flows.unrecognized.out.person", kind: "handoff" },
    ],
    notes: [{ text: "flows.unrecognized.remarks.identity" }, { text: "flows.unrecognized.remarks.confirm" }],
  },
  {
    id: "fraud",
    title: "flows.fraud.title",
    lede: "flows.fraud.lede",
    steps: [
      { title: "flows.step.report", quote: "flows.fraud.report" },
      IDENTIFY,
      VERIFY,
      { title: "flows.step.reviewMovements", tool: "transaction.list_recent", state: "VERIFIED" },
      { title: "flows.step.block", tool: "card.block · SUSPICIOUS_ACTIVITY", state: "VERIFIED" },
    ],
    outcomes: [
      { text: "flows.fraud.out.auto", kind: "auto" },
      { text: "flows.fraud.out.handoff", kind: "handoff" },
      { text: "flows.fraud.out.urgent", kind: "urgent" },
    ],
    notes: [{ text: "flows.fraud.remarks.noCharge" }, { text: "flows.fraud.remarks.vishing", pending: true }],
    example: [
      { who: "customer", text: "flows.fraud.example.customer1" },
      { who: "assistant", text: "flows.fraud.example.assistant1" },
      { who: "trace", raw: "customer.match → otp.send → otp.verify · VERIFIED" },
      { who: "assistant", text: "flows.fraud.example.assistant2" },
      { who: "customer", text: "flows.fraud.example.customer2" },
      { who: "trace", text: "flows.fraud.example.trace2" },
      { who: "assistant", text: "flows.fraud.example.assistant3" },
    ],
  },
  {
    id: "lost",
    title: "flows.lost.title",
    lede: "flows.lost.lede",
    steps: [
      { title: "flows.step.report", quote: "flows.lost.report" },
      IDENTIFY,
      VERIFY,
      { title: "flows.step.pickCard", tool: "card.list", state: "VERIFIED" },
      { title: "flows.step.block", tool: "card.block · LOST / STOLEN", state: "VERIFIED" },
    ],
    outcomes: [
      { text: "flows.lost.out.auto", kind: "auto" },
      { text: "flows.lost.out.locked", kind: "handoff" },
      { text: "flows.lost.out.thirdParty", kind: "handoff" },
    ],
    notes: [{ text: "flows.lost.remarks.cards" }, { text: "flows.lost.remarks.noCharge" }],
  },
  {
    id: "balance",
    title: "flows.balance.title",
    lede: "flows.balance.lede",
    steps: [
      { title: "flows.step.report", quote: "flows.balance.report" },
      IDENTIFY,
      VERIFY,
      { title: "flows.step.answer", tool: "account.get_summary", state: "VERIFIED" },
    ],
    outcomes: [
      { text: "flows.balance.out.enabled", kind: "auto" },
      { text: "flows.balance.out.disabled", kind: "info" },
      { text: "flows.balance.out.payments", kind: "auto" },
    ],
    notes: [],
  },
];

export function FlowsScreen() {
  const { t } = useI18n();
  const { api } = useAppServices();
  const [snapshot, send] = useMachine(flowsMachine, { input: { api } });
  const { policy, tools, error } = snapshot.context;

  const heading = (
    <h1 className="h1" id="flows-title">
      {t("flows.title")}
    </h1>
  );

  if (snapshot.matches("loading")) {
    return (
      <section className="bo-screen" aria-labelledby="flows-title">
        {heading}
        <p className="pb-t-small" role="status">
          {t("common.loading")}
        </p>
      </section>
    );
  }

  if (snapshot.matches("failed") || !policy || !tools) {
    return (
      <section className="bo-screen" aria-labelledby="flows-title">
        {heading}
        <Alert
          tone="caution"
          eyebrow={t("flows.title")}
          action={
            <button type="button" className="pb-btn pb-btn--secondary pb-btn--sm" onClick={() => send({ type: "RETRY" })}>
              {t("common.retry")}
            </button>
          }
        >
          {error === "unavailable" ? t("errors.unavailable") : t("flows.loadFailed")}
        </Alert>
      </section>
    );
  }

  return (
    <section className="bo-screen" aria-labelledby="flows-title">
      <div className="bo-bar">
        {heading}
        <span className="pb-t-small">
          {t("flows.versions", { tools: tools.version, policy: policy.version })} · {t("flows.mode", { mode: t(policy.amount_mode === "flag" ? "guardrails.mode.flagLabel" : "guardrails.mode.blockLabel") })}
        </span>
      </div>
      <p className="bo-help">
        <Identifiers text={t("flows.lede")} />
      </p>
      <StateMachine />
      <ToolsByState tools={tools} />
      {FLOWS.map((flow) => (
        <FlowCard key={flow.id} flow={flow} balanceEnabled={(tools.tools["account.get_summary"] ?? []).length > 0} />
      ))}
    </section>
  );
}

export function StateMachine() {
  const { t } = useI18n();
  return (
    <section className="pb-card bo-section" aria-labelledby="fsm-title">
      <h2 className="h2" id="fsm-title">
        {t("flows.fsm.title")}
      </h2>
      <p>
        <Identifiers text={t("flows.fsm.lede")} />
      </p>
      <ol className="bo-path">
        {PATH.map(({ state, tool }) => (
          <li key={state} className="bo-path__item">
            <span className="pb-cut bo-node bo-flowstate" data-state={chipState(state)}>
              <StateChip state={state} words />
              <span className="pb-t-small">{t(`flows.fsm.states.${state}` as MessageKey)}</span>
            </span>
            {tool && (
              <span className="bo-edge" aria-label={t("flows.fsm.then", { tool })}>
                <span className="pb-t-mono">{tool}</span>
                <Icon name="arrow" />
              </span>
            )}
          </li>
        ))}
      </ol>
      <ul className="bo-exits">
        <li>
          <StateChip state="LOCKED" words />{" "}
          <span>
            <Identifiers text={t("flows.fsm.toLocked")} />
          </span>
        </li>
        <li>
          <StateChip state="HANDED_OFF" words />{" "}
          <span>
            <Identifiers text={t("flows.fsm.toHandedOff")} />
          </span>
        </li>
      </ul>
    </section>
  );
}

export function ToolsByState({ tools }: { tools: ToolPolicyResponse }) {
  const { t } = useI18n();
  return (
    <section className="pb-card bo-section" aria-labelledby="matrix-title">
      <div className="bo-bar">
        <h2 className="h2" id="matrix-title">
          {t("flows.matrix.title")}
        </h2>
        <a href="#/guardrails" className="pb-action">
          {t("flows.matrix.edit")}
          <Icon name="arrow" />
        </a>
      </div>
      <p>
        <Identifiers text={t("flows.matrix.lede")} />
      </p>
      <div className="pb-mx bo-mx">
        <table>
          <thead>
            <tr>
              <th scope="col">{t("flows.matrix.tool")}</th>
              {STATES.map((state) => (
                <th key={state} scope="col">
                  <StateChip state={state} words />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Object.keys(tools.code_floor).map((tool) => {
              const enabled = tools.tools[tool] ?? [];
              const disabled = enabled.length === 0;
              return (
                <tr key={tool} data-disabled={disabled ? "true" : undefined}>
                  <th scope="row">
                    <span className="pb-mx__tool">
                      <b className="pb-t-mono">{tool}</b>
                      {disabled && <span className="pb-t-small">{t("flows.matrix.disabled")}</span>}
                    </span>
                  </th>
                  {STATES.map((state) => {
                    const on = enabled.includes(state);
                    const label = t(on ? "flows.matrix.allowed" : "flows.matrix.notAllowed", { tool, state: t(`enums.state.${state}`) });
                    return (
                      <td key={state}>
                        {on ? (
                          <span className="pb-mx__cell" role="img" aria-checked="true" aria-label={label}>
                            <Icon name="check" />
                          </span>
                        ) : (
                          <span className="pb-mx__off" role="img" aria-label={label}>
                            ·
                          </span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function FlowCard({ flow, balanceEnabled }: { flow: Flow; balanceEnabled: boolean }) {
  const { t } = useI18n();
  const titleId = `flow-${flow.id}`;
  return (
    <section className="pb-card bo-section" aria-labelledby={titleId}>
      <div className="bo-bar">
        <h2 className="h2" id={titleId}>
          {t(flow.title)}
        </h2>
        {flow.id === "balance" && <span className="pb-t-small">{t(balanceEnabled ? "flows.balance.today.enabled" : "flows.balance.today.disabled")}</span>}
      </div>
      <p>
        <Identifiers text={t(flow.lede)} />
      </p>
      <ol className="pb-flow pb-flow--col" role="list">
        {flow.steps.map((step, index) => (
          <li key={index} className="pb-flow__item">
            <p className="pb-flow__title">{t(step.title)}</p>
            {step.quote && <p className="pb-t-small">{t(step.quote)}</p>}
            {step.tool && <p className="pb-t-mono">{step.tool}</p>}
            {step.state && step.state !== flow.steps[index - 1]?.state && (
              <span className="pb-flow__state">
                <StateChip state={step.state} words />
              </span>
            )}
          </li>
        ))}
      </ol>
      <h3 className="pb-t-h3">{t("flows.outcomes")}</h3>
      <ul className="bo-outcomes">
        {flow.outcomes.map((outcome) => {
          const { attr, icon, word } = OUTCOME_CHIP[outcome.kind];
          return (
            <li key={outcome.text} className="bo-outcome">
              <span className="pb-chip" {...attr}>
                <Icon name={icon} />
                {t(word)}
              </span>
              <span>
                <Identifiers text={t(outcome.text)} />
              </span>
            </li>
          );
        })}
      </ul>
      {flow.notes.some((note) => !note.pending) && (
        <div className="bo-notes">
          <p className="pb-t-label">{t("flows.notes")}</p>
          <ul className="bo-notelist">
            {flow.notes
              .filter((note) => !note.pending)
              .map((note) => (
                <li key={note.text}>
                  <Icon name="info" />
                  <span className="pb-t-small">
                    <Identifiers text={t(note.text)} />
                  </span>
                </li>
              ))}
          </ul>
        </div>
      )}
      {flow.notes
        .filter((note) => note.pending)
        .map((note) => (
          <Alert key={note.text} tone="caution" eyebrow={t("flows.notePending")}>
            <Identifiers text={t(note.text)} />
          </Alert>
        ))}
      {flow.example && (
        <div className="bo-example">
          <h3 className="pb-t-h3">{t("flows.example")}</h3>
          <ol className="bo-example__log">
            {flow.example.map((line, index) =>
              line.who === "trace" ? (
                <li key={index} className="bo-example__trace pb-t-mono">
                  {"raw" in line ? line.raw : t(line.text)}
                </li>
              ) : (
                <li key={index} className={`pb-msg pb-msg--${line.who}`}>
                  <span className="pb-msg__meta">{t(line.who === "customer" ? "flows.customer" : "flows.assistant")}</span>
                  {t(line.text)}
                </li>
              ),
            )}
          </ol>
        </div>
      )}
    </section>
  );
}
