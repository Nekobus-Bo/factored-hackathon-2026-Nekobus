// HandoffCard: the case file a human agent receives (design system: HandoffCard). Everything on it is
// what banking-core stored with the handoff: `summary.verified_facts` are facts a tool returned,
// `open_questions` are proposals the model made and nothing verified. The card never proposes a
// resolution: "El asistente no resuelve disputas."

import { VerificationStateSchema, type HandoffDetail, type JsonValue } from "@pattern-blue/contracts";
import type { ReactNode } from "react";
import { useI18n } from "./context";
import { dateTimeText, money, waitText } from "./format";
import { HandoffStatusChip, Icon, PriorityChip, StateChip } from "./ui";

/** `**** **** **** 4821` as the design system prints a mask: `•••• •••• •••• 4821`. */
const dots = (masked: string) => masked.replaceAll("*", "•");

const isRecord = (value: JsonValue | undefined): value is { [key: string]: JsonValue } =>
  typeof value === "object" && value !== null && !Array.isArray(value);

function Fact({ name, value }: { name: string; value: JsonValue }) {
  const { t } = useI18n();

  if (name === "verification_state" && typeof value === "string" && VerificationStateSchema.safeParse(value).success) {
    return <StateChip state={value} />;
  }
  if (typeof value === "boolean") return <>{value ? t("common.yes") : t("common.no")}</>;
  if (Array.isArray(value)) {
    if (value.length === 0) return <>{t("common.none")}</>;
    return (
      <span className="bo-tags">
        {value.map((item, index) => (
          <span key={index} className="pb-tag">
            {typeof item === "string" ? item : JSON.stringify(item)}
          </span>
        ))}
      </span>
    );
  }
  if (name === "disputed_transaction" && isRecord(value)) {
    const amount = value.amount_minor;
    const currency = value.currency;
    return (
      <dl className="pb-kv bo-kv-nested">
        {typeof value.merchant === "string" && (
          <>
            <dt>{t("handoff.txn.merchant")}</dt>
            <dd className="pb-kv__text">{value.merchant}</dd>
          </>
        )}
        {typeof amount === "number" && typeof currency === "string" && (
          <>
            <dt>{t("handoff.txn.amount")}</dt>
            <dd>{money(amount, currency)}</dd>
          </>
        )}
        {typeof value.posted_at === "string" && (
          <>
            <dt>{t("handoff.txn.postedAt")}</dt>
            <dd>{dateTimeText(value.posted_at)}</dd>
          </>
        )}
        {typeof value.card_masked === "string" && (
          <>
            <dt>{t("handoff.txn.card")}</dt>
            <dd>{dots(value.card_masked)}</dd>
          </>
        )}
        {typeof value.transaction_id === "string" && (
          <>
            <dt>{t("handoff.txn.id")}</dt>
            <dd>{value.transaction_id}</dd>
          </>
        )}
      </dl>
    );
  }
  if (value === null) return <>{t("common.empty")}</>;
  if (typeof value === "object") return <>{JSON.stringify(value)}</>;
  return <>{String(value)}</>;
}

const FACT_LABELS = ["verification_state", "customer_identified", "policy_flags", "disputed_transaction"] as const;
type FactLabel = (typeof FACT_LABELS)[number];
const isFactLabel = (name: string): name is FactLabel => (FACT_LABELS as readonly string[]).includes(name);

function ActionStep({ action }: { action: HandoffDetail["summary"]["actions_taken"][number] }) {
  const { t } = useI18n();
  if (typeof action === "string") {
    return (
      <li>
        <Icon name="check" />
        <span>{action}</span>
      </li>
    );
  }
  const name = typeof action.action === "string" ? action.action : JSON.stringify(action);
  const decision = typeof action.decision === "string" ? action.decision : null;
  const reasonCode = typeof action.reason_code === "string" ? action.reason_code : null;
  const audit = typeof action.audit_id === "string" ? action.audit_id : null;
  const decisionWord =
    decision === "allowed" || decision === "refused" || decision === "error" ? `${t(`enums.decision.${decision}`)} (${decision})` : decision;
  const reasonWord = reasonCode
    ? reasonCode in reasonCodeKeys
      ? `${t(reasonCodeKeys[reasonCode as keyof typeof reasonCodeKeys])} (${reasonCode})`
      : reasonCode
    : null;
  const details = [decisionWord, reasonWord, audit].filter((part): part is string => part !== null && part !== "");
  return (
    <li>
      <Icon name={decision === null || decision === "allowed" ? "check" : "x"} />
      <span>
        {name}
        {details.length > 0 && <small>{details.join(" · ")}</small>}
      </span>
    </li>
  );
}

const reasonCodeKeys = {
  STATE_NOT_ALLOWED: "enums.reasonCode.STATE_NOT_ALLOWED",
  POLICY_BLOCKED: "enums.reasonCode.POLICY_BLOCKED",
  POLICY_FLAGGED: "enums.reasonCode.POLICY_FLAGGED",
  RATE_LIMITED: "enums.reasonCode.RATE_LIMITED",
  NOT_MATCHED: "enums.reasonCode.NOT_MATCHED",
  NOT_IMPLEMENTED: "enums.reasonCode.NOT_IMPLEMENTED",
  SESSION_BUSY: "enums.reasonCode.SESSION_BUSY",
  INVALID_ARGUMENTS: "enums.reasonCode.INVALID_ARGUMENTS",
  CODE_FLOOR_VIOLATION: "enums.reasonCode.CODE_FLOOR_VIOLATION",
  CONFIRMATION_REQUIRED: "enums.reasonCode.CONFIRMATION_REQUIRED",
  INTERNAL_ERROR: "enums.reasonCode.INTERNAL_ERROR",
} as const;

const methodKeys = {
  none: "enums.verificationMethod.none",
  document_match_only: "enums.verificationMethod.document_match_only",
  document_match_otp_pending: "enums.verificationMethod.document_match_otp_pending",
  document_match_and_otp: "enums.verificationMethod.document_match_and_otp",
  locked_after_failed_verification: "enums.verificationMethod.locked_after_failed_verification",
  previously_handed_off: "enums.verificationMethod.previously_handed_off",
} as const;

export function HandoffCard({ detail, now, me, actions }: { detail: HandoffDetail; now: number; me?: string; actions?: ReactNode }) {
  const { t } = useI18n();
  const { summary } = detail;
  const titleId = `case-${detail.handoff_ref}`;
  const facts = Object.entries(summary.verified_facts);
  const method = summary.verification_method;
  const waiting = waitText(Date.parse(detail.created_at), now);

  const assignment =
    detail.assigned_agent === null
      ? detail.queue_position !== null
        ? t("handoff.position", { position: detail.queue_position })
        : null
      : me !== undefined && detail.assigned_agent === me
        ? t("handoff.assignedToYou")
        : t("handoff.assignedTo", { agent: detail.assigned_agent });

  return (
    <article className={`pb-card pb-handoff${detail.priority === "URGENT" ? "" : " bo-handoff--flat"}`} aria-labelledby={titleId}>
      {detail.priority === "URGENT" && <span className="pb-hazard" aria-hidden="true" />}
      <header>
        <div className="pb-handoff__head">
          <h2 className="bo-case-id" id={titleId}>
            <a className="pb-caseid" href={`#/handoffs/${detail.handoff_ref}`}>
              {detail.handoff_ref}
            </a>
          </h2>
          <PriorityChip priority={detail.priority} />
          <HandoffStatusChip status={detail.status} />
        </div>
        <div className="pb-handoff__meta">
          <span className="pb-tag">{detail.department}</span>
          <span className="pb-tag">{detail.reason}</span>
          <span className="pb-t-small">
            {[t(`enums.department.${detail.department}`), t(`enums.reason.${detail.reason}`), t("handoff.waiting", { time: waiting }), assignment]
              .filter((part) => part !== null)
              .join(" · ")}
          </span>
        </div>
      </header>

      <section className="pb-handoff__sec" aria-labelledby={`${titleId}-facts`}>
        <h3 id={`${titleId}-facts`}>{t("handoff.facts")}</h3>
        <dl className="pb-kv">
          <dt>{t("handoff.verification")}</dt>
          <dd className="pb-kv__text">
            {method in methodKeys ? t(methodKeys[method as keyof typeof methodKeys]) : null}
            {method in methodKeys ? " " : null}
            <span className="pb-t-mono">{method in methodKeys ? `(${method})` : method}</span>
          </dd>
          {facts.map(([name, value]) => (
            <FactRow key={name} name={name} value={value} />
          ))}
        </dl>
        {facts.length === 0 && <p className="pb-t-small">{t("handoff.noFacts")}</p>}
      </section>

      <section className="pb-handoff__sec" aria-labelledby={`${titleId}-acts`}>
        <h3 id={`${titleId}-acts`}>{t("handoff.actions")}</h3>
        {summary.actions_taken.length === 0 ? (
          <p className="pb-t-small">{t("handoff.noActions")}</p>
        ) : (
          <ul className="pb-steps">
            {summary.actions_taken.map((action, index) => (
              <ActionStep key={index} action={action} />
            ))}
          </ul>
        )}
      </section>

      <section className="pb-handoff__sec" aria-labelledby={`${titleId}-open`}>
        <h3 id={`${titleId}-open`}>{t("handoff.questions")}</h3>
        {summary.open_questions.length === 0 ? (
          <p className="pb-t-small">{t("handoff.noQuestions")}</p>
        ) : (
          <ol className="pb-questions">
            {summary.open_questions.map((question, index) => (
              <li key={index}>
                <span>
                  {question.text}
                  <small className="pb-t-small bo-source">
                    {t("handoff.questionSource", { source: question.source })}
                    {question.source === "model_unverified" ? ` (${t("handoff.sourceModel")})` : ""}
                  </small>
                </span>
              </li>
            ))}
          </ol>
        )}
      </section>

      {actions && <div className="pb-handoff__actions">{actions}</div>}
      <p className="pb-t-small bo-note">{t("handoff.footnote")}</p>
    </article>
  );
}

function FactRow({ name, value }: { name: string; value: JsonValue }) {
  const { t } = useI18n();
  const label = isFactLabel(name) ? t(`handoff.factLabels.${name}`) : name;
  return (
    <>
      <dt>{label}</dt>
      <dd>
        <Fact name={name} value={value} />
      </dd>
    </>
  );
}
