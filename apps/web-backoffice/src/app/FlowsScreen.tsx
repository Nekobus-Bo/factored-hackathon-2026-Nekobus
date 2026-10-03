// The flows screen: how a session moves through the verification state machine, which tools the policy in
// force allows in each state, and the assistant's main flows end to end. Read only; it draws what
// banking-core enforces (ADR-0003, ADR-0016) and links to Guardrails for changes. The diagrams are plain
// lists styled with the tokens, so they wrap on a phone and read in order with a screen reader.

import type { ToolPolicyResponse, VerificationState } from "@pattern-blue/contracts";
import { useMachine } from "@xstate/react";
import type { MessageKey } from "../i18n";
import { flowsMachine } from "../machines/flows";
import { useAppServices, useI18n } from "./context";
import { Alert, chipState, StateChip } from "./ui";

export const STATES: readonly VerificationState[] = ["ANONYMOUS", "IDENTIFIED", "OTP_PENDING", "VERIFIED", "LOCKED", "HANDED_OFF"];

/** The forward path to VERIFIED: each state and the tool that leaves it (contracts VERIFICATION_PATH). */
const PATH: readonly { state: VerificationState; tool?: string }[] = [
  { state: "ANONYMOUS", tool: "customer.match" },
  { state: "IDENTIFIED", tool: "otp.send" },
  { state: "OTP_PENDING", tool: "otp.verify" },
  { state: "VERIFIED" },
];

type Tone = "success" | "handoff" | "fraud" | "neutral";

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
  outcomes: { text: MessageKey; tone: Tone }[];
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
      { text: "flows.unrecognized.out.auto", tone: "success" },
      { text: "flows.unrecognized.out.handoff", tone: "handoff" },
      { text: "flows.unrecognized.out.person", tone: "neutral" },
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
      { text: "flows.fraud.out.auto", tone: "success" },
      { text: "flows.fraud.out.handoff", tone: "fraud" },
      { text: "flows.fraud.out.urgent", tone: "fraud" },
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
      { text: "flows.lost.out.auto", tone: "success" },
      { text: "flows.lost.out.locked", tone: "handoff" },
      { text: "flows.lost.out.thirdParty", tone: "neutral" },
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
      { text: "flows.balance.out.enabled", tone: "success" },
      { text: "flows.balance.out.disabled", tone: "neutral" },
      { text: "flows.balance.out.payments", tone: "success" },
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
          {t("flows.versions", { tools: tools.version, policy: policy.version })} · {t("flows.mode", { mode: policy.amount_mode })}
        </span>
      </div>
      <p className="bo-help">{t("flows.lede")}</p>
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
      <p>{t("flows.fsm.lede")}</p>
      <ol className="bo-path">
        {PATH.map(({ state, tool }) => (
          <li key={state} className="bo-path__item">
            <span className="bo-node bo-flowstate" data-state={chipState(state)}>
              <StateChip state={state} />
              <span className="pb-t-small">{t(`flows.fsm.states.${state}` as MessageKey)}</span>
            </span>
            {tool && (
              <span className="bo-edge" aria-label={t("flows.fsm.then", { tool })}>
                <span className="bo-raw">{tool}</span>
              </span>
            )}
          </li>
        ))}
      </ol>
      <ul className="bo-exits">
        <li>
          <StateChip state="LOCKED" /> <span>{t("flows.fsm.toLocked")}</span>
        </li>
        <li>
          <StateChip state="HANDED_OFF" /> <span>{t("flows.fsm.toHandedOff")}</span>
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
        <a href="#/guardrails" className="pb-t-small">
          {t("flows.matrix.edit")}
        </a>
      </div>
      <p>{t("flows.matrix.lede")}</p>
      <div className="bo-scroll">
        <table className="bo-matrix">
          <thead>
            <tr>
              <th scope="col">{t("flows.matrix.tool")}</th>
              {STATES.map((state) => (
                <th key={state} scope="col">
                  {state}
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
                  <th scope="row" className="bo-raw">
                    {tool}
                    {disabled && <span className="pb-t-small"> · {t("flows.matrix.disabled")}</span>}
                  </th>
                  {STATES.map((state) => {
                    const on = enabled.includes(state);
                    return (
                      <td key={state} className="bo-flowstate" data-on={on ? "true" : "false"} data-state={chipState(state)}>
                        <span aria-label={t(on ? "flows.matrix.allowed" : "flows.matrix.notAllowed", { state })}>{on ? "●" : "—"}</span>
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
      <p>{t(flow.lede)}</p>
      <ol className="bo-steps">
        {flow.steps.map((step, index) => (
          <li key={index} className="bo-step bo-flowstate" data-state={step.state ? chipState(step.state) : undefined}>
            <b>
              {index + 1} · {t(step.title)}
            </b>
            {step.quote && <span className="pb-t-small">{t(step.quote)}</span>}
            {step.tool && <span className="bo-raw pb-t-small">{step.tool}</span>}
          </li>
        ))}
      </ol>
      <h3>{t("flows.outcomes")}</h3>
      <ul className="bo-outcomes">
        {flow.outcomes.map((outcome) => (
          <li key={outcome.text} className="bo-outcome" data-tone={outcome.tone}>
            {t(outcome.text)}
          </li>
        ))}
      </ul>
      {flow.notes.length > 0 && (
        <ul className="bo-flow-notes">
          {flow.notes.map((note) => (
            <li key={note.text} data-pending={note.pending ? "true" : undefined}>
              {t(note.text)}
            </li>
          ))}
        </ul>
      )}
      {flow.example && (
        <div className="bo-example">
          <h3>{t("flows.example")}</h3>
          <ol className="bo-example__log">
            {flow.example.map((line, index) => (
              <li key={index} data-who={line.who}>
                {line.who !== "trace" && <span className="pb-t-small">{t(line.who === "customer" ? "flows.customer" : "flows.assistant")}</span>}
                <span>{"raw" in line ? line.raw : t(line.text)}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}
