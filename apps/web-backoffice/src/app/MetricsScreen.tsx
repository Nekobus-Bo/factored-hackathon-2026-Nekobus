// Metrics at a glance (the declutter review of 2026-10-02): four numbers first, each against the window
// before (ADR-0018). Whether the assistant helped leads, because it is the one number about the customer's
// experience. Then the cases whose customer said no, and what needs a look; the tables stay below, closed.
// Everything is a count banking-core returns: the only figures derived here are shares and differences.

import { DepartmentSchema, HANDOFF_PRIORITY_ORDER, HandoffOutcomeSchema, HandoffStatusSchema, type MetricsResponse } from "@pattern-blue/contracts";
import { useMachine } from "@xstate/react";
import { useState, type CSSProperties, type ReactNode } from "react";
import { METRICS_WINDOWS, metricsMachine } from "../machines/metrics";
import { useReasonWord } from "./CaseFacts";
import { useAppServices, useI18n, useNow } from "./context";
import { clockText, percent, waitText } from "./format";
import { Alert, CaseRef, DecisionChip, Icon } from "./ui";

const DECISION_ORDER = { allowed: 0, refused: 1, error: 2 } as const;
const DECISION_GAUGE = { allowed: "decided", refused: "caution", error: "blocked" } as const;

type ToolCall = MetricsResponse["tool_calls"][number];

/** A share in whole percent, or null when there is nothing to divide by. */
const shareOf = (part: number, total: number): number | null => (total > 0 ? Math.round((part / total) * 100) : null);

function Gauge({ on, state, label, valueNow, valueMax }: { on: number; state: string; label?: string; valueNow?: number; valueMax?: number }) {
  return (
    <span
      className="pb-gauge pb-gauge--sm"
      data-state={state}
      style={{ "--n": 20, "--on": on } as CSSProperties}
      role={label ? "meter" : undefined}
      aria-label={label}
      aria-valuemin={label ? 0 : undefined}
      aria-valuemax={label ? valueMax : undefined}
      aria-valuenow={label ? valueNow : undefined}
    >
      <span className="pb-gauge__track">
        <span className="pb-gauge__fill" />
      </span>
    </span>
  );
}

/** "+6 pts" or "−3": the change against the previous window. Only shares have a better direction. */
function Delta({ value, unit, judged, note }: { value: number | null; unit: "pts" | "count"; judged: boolean; note?: string }) {
  const { t } = useI18n();
  if (value === null) return null;
  const text = value === 0 ? t("metrics.delta.same") : `${value > 0 ? "+" : "−"}${Math.abs(value)}${unit === "pts" ? ` ${t("metrics.delta.pts")}` : ""}`;
  return (
    <span className="pb-delta" data-dir={value > 0 ? "up" : value < 0 ? "down" : undefined} data-neutral={judged ? undefined : ""}>
      <Icon name={value === 0 ? "minus" : "chev1"} />
      {text}
      {note && <span>{note}</span>}
    </span>
  );
}

function Kpi({ label, lead = false, children }: { label: string; lead?: boolean; children: ReactNode }) {
  return (
    <section className={`pb-card pb-kpi${lead ? " pb-kpi--lead" : ""}`} aria-label={label}>
      <p className="pb-kpi__label">{label}</p>
      {children}
    </section>
  );
}

export function GlanceNumbers({ data }: { data: MetricsResponse }) {
  const { t } = useI18n();
  const { feedback, previous, otp, queue } = data;
  const answers = feedback.helpful + feedback.not_helpful;
  const helped = shareOf(feedback.helpful, answers);
  const helpedBefore = shareOf(previous.feedback.helpful, previous.feedback.helpful + previous.feedback.not_helpful);
  const verified = shareOf(otp.verified, otp.sent);
  const verifiedBefore = shareOf(previous.otp.verified, previous.otp.sent);

  return (
    <div className="pb-kpis">
      <Kpi label={t("metrics.helped.label")} lead>
        {helped === null ? (
          <p className="pb-kpi__sub">{t("metrics.helped.none")}</p>
        ) : (
          <>
            <p className="pb-kpi__value">
              {helped}%<small>{t("metrics.helped.value")}</small>
            </p>
            <Gauge on={Math.round((helped / 100) * 20)} state="decided" label={t("metrics.helped.meter", { yes: feedback.helpful, answers })} valueNow={feedback.helpful} valueMax={answers} />
            <p className="pb-kpi__sub">
              <b>{t("metrics.helped.split", { yes: feedback.helpful, no: feedback.not_helpful })}</b> {t("metrics.helped.of", { answers })}
            </p>
            <Delta value={helpedBefore === null ? null : helped - helpedBefore} unit="pts" judged note={t("metrics.delta.vsPrevious", { hours: data.window_hours })} />
          </>
        )}
        <p className="pb-kpi__foot">{t("metrics.helped.foot", { answers, handoffs: data.handoffs.total })}</p>
      </Kpi>
      <Kpi label={t("metrics.verified.label")}>
        {verified === null ? (
          <p className="pb-kpi__sub">{t("metrics.verified.none")}</p>
        ) : (
          <>
            <p className="pb-kpi__value">{verified}%</p>
            <p className="pb-kpi__sub">
              <b>{t("metrics.verified.of", { verified: otp.verified, sent: otp.sent })}</b>
            </p>
            <p className="pb-kpi__sub">{t("metrics.verified.failed", { failed: otp.failed })}</p>
            <Delta value={verifiedBefore === null ? null : verified - verifiedBefore} unit="pts" judged />
          </>
        )}
      </Kpi>
      <Kpi label={t("metrics.cards.label")}>
        <p className="pb-kpi__value">{data.cards_blocked}</p>
        <p className="pb-kpi__sub">{t("metrics.cards.sub")}</p>
        <Delta value={data.cards_blocked - previous.cards_blocked} unit="count" judged={false} />
      </Kpi>
      <Kpi label={t("metrics.cases.label")}>
        <p className="pb-kpi__value">{data.handoffs.total}</p>
        <p className="pb-kpi__sub">
          <b>{t("metrics.cases.waiting", { waiting: queue.waiting })}</b> {t("metrics.cases.urgent", { urgent: queue.urgent })}
        </p>
        <Delta value={data.handoffs.total - previous.handoffs_total} unit="count" judged={false} />
      </Kpi>
    </div>
  );
}

export function NotHelpfulList({ data }: { data: MetricsResponse }) {
  const { t } = useI18n();
  return (
    <section className="pb-card" aria-labelledby="m-no">
      <h2 className="pb-list__h" id="m-no">
        {t("metrics.no.title")}
      </h2>
      {data.recent_not_helpful.length === 0 ? (
        <p className="pb-t-small">{t("metrics.no.empty")}</p>
      ) : (
        <ul className="pb-list">
          {data.recent_not_helpful.map((item) => (
            <li key={item.handoff_ref} data-tone="no">
              <Icon name="x" />
              <span>
                {t(`enums.reason.${item.reason}`)}
                <small>
                  <CaseRef value={item.handoff_ref} /> · {clockText(item.recorded_at)}
                </small>
              </span>
              <a className="pb-action" href={`#/handoffs/${item.handoff_ref}`}>
                {t("queue.open")}
                <Icon name="arrow" />
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function ToReviewList({ data, now, onOpenTools }: { data: MetricsResponse; now: number; onOpenTools: () => void }) {
  const { t } = useI18n();
  const sum = (decision: string) => data.tool_calls.filter((row) => row.decision === decision).reduce((total, row) => total + row.count, 0);
  const total = data.tool_calls.reduce((all, row) => all + row.count, 0);
  const errors = sum("error");
  const refused = sum("refused");
  const errorTools = [...new Set(data.tool_calls.filter((row) => row.decision === "error").map((row) => row.action))].join(", ");
  const lines: ReactNode[] = [];
  if (errors > 0) {
    lines.push(
      <li key="errors" data-tone="critical">
        <Icon name="critical" />
        <span>
          {errors === 1 ? t("metrics.look.errorOne") : t("metrics.look.errors", { count: errors })}
          <small>{errorTools}</small>
        </span>
        <button type="button" className="pb-action" onClick={onOpenTools}>
          {t("metrics.look.see")}
          <Icon name="arrow" />
        </button>
      </li>,
    );
  }
  if (refused > 0) {
    lines.push(
      <li key="refused" data-tone="policy">
        <Icon name="shield-check" />
        <span>
          {refused === 1 ? t("metrics.look.refusedOne") : t("metrics.look.refused", { count: refused })}
          <small>{t("metrics.look.refusedShare", { share: percent(refused, total), total })}</small>
        </span>
        <button type="button" className="pb-action" onClick={onOpenTools}>
          {t("metrics.look.see")}
          <Icon name="arrow" />
        </button>
      </li>,
    );
  }
  if (data.queue.waiting > 0) {
    lines.push(
      <li key="waiting">
        <Icon name="clock" />
        <span>
          {data.queue.waiting === 1 ? t("metrics.look.waitingOne") : t("metrics.look.waiting", { count: data.queue.waiting })}
          {data.queue.oldest_created_at && <small>{t("metrics.look.oldest", { wait: waitText(Date.parse(data.queue.oldest_created_at), now) })}</small>}
        </span>
        <a className="pb-action" href="#/">
          {t("metrics.look.toQueue")}
          <Icon name="arrow" />
        </a>
      </li>,
    );
  }
  return (
    <section className="pb-card" aria-labelledby="m-look">
      <h2 className="pb-list__h" id="m-look">
        {t("metrics.look.title")}
      </h2>
      {lines.length === 0 ? <p className="pb-t-small">{t("metrics.look.empty")}</p> : <ul className="pb-list">{lines}</ul>}
    </section>
  );
}

/** Tool calls, the tool named once per group; the decision and reason as one phrase in words. */
export function ToolCallsTable({ rows }: { rows: readonly ToolCall[] }) {
  const { t } = useI18n();
  const reasonWord = useReasonWord();
  const total = rows.reduce((sum, row) => sum + row.count, 0);
  const sorted = [...rows].sort((a, b) => a.action.localeCompare(b.action) || DECISION_ORDER[a.decision] - DECISION_ORDER[b.decision]);
  const groups: ToolCall[][] = [];
  for (const row of sorted) {
    const last = groups.at(-1);
    if (last && last[0]?.action === row.action) last.push(row);
    else groups.push([row]);
  }
  return (
    <table className="pb-mtable" aria-label={t("metrics.tools.title")}>
      <thead>
        <tr>
          <th scope="col">{t("metrics.tools.tool")}</th>
          <th scope="col">{t("metrics.tools.result")}</th>
          <th scope="col" data-col="count">
            {t("metrics.tools.calls")}
          </th>
          <th scope="col">{t("metrics.tools.share")}</th>
        </tr>
      </thead>
      {groups.map((group) => (
        <tbody key={group[0]?.action}>
          {group.map((row, index) => {
            const reason = row.reason_code ? reasonWord(row.reason_code) : null;
            return (
              <tr key={`${row.decision}-${row.reason_code ?? ""}`}>
                <td data-col="name">{index === 0 ? row.action : ""}</td>
                <td>
                  <DecisionChip decision={row.decision} title={[row.decision, row.reason_code].filter(Boolean).join(" · ")} />
                  {reason && <span className="pb-reason">{reason}</span>}
                </td>
                <td data-col="count">{row.count}</td>
                <td>
                  <span className="pb-share">
                    <Gauge
                      on={row.count > 0 ? Math.max(1, Math.round((row.count / Math.max(total, 1)) * 20)) : 0}
                      state={DECISION_GAUGE[row.decision]}
                      label={t("metrics.tools.meter", { action: row.action, count: row.count, total })}
                      valueNow={row.count}
                      valueMax={total}
                    />
                    {percent(row.count, total)}%
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      ))}
    </table>
  );
}

function Distribution({ title, rows, total }: { title: string; rows: { raw: string; word: string; count: number }[]; total: number }) {
  const { t } = useI18n();
  return (
    <div className="bo-dist">
      <h3 className="pb-t-h3">{title}</h3>
      <table className="pb-mtable" aria-label={title}>
        <thead>
          <tr>
            <th scope="col">{t("metrics.handoffs.value")}</th>
            <th scope="col" data-col="count">
              {t("metrics.handoffs.count")}
            </th>
            <th scope="col" data-col="count">
              {t("metrics.handoffs.share")}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.raw}>
              <td title={row.raw}>{row.word}</td>
              <td data-col="count">{row.count}</td>
              <td data-col="count">{percent(row.count, total)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function HandoffTables({ handoffs }: { handoffs: MetricsResponse["handoffs"] }) {
  const { t } = useI18n();
  const status = HandoffStatusSchema.options.map((raw) => ({ raw, word: t(`enums.status.${raw}`), count: handoffs.by_status[raw] ?? 0 }));
  const priority = HANDOFF_PRIORITY_ORDER.map((raw) => ({ raw, word: t(`enums.priority.${raw}`), count: handoffs.by_priority[raw] ?? 0 }));
  const department = DepartmentSchema.options.map((raw) => ({ raw, word: t(`enums.department.${raw}`), count: handoffs.by_department[raw] ?? 0 }));
  const closed = handoffs.by_status.CLOSED ?? 0;
  const outcome = HandoffOutcomeSchema.options.map((raw) => ({ raw, word: t(`enums.outcome.${raw}`), count: handoffs.by_outcome[raw] ?? 0 }));
  return (
    <div className="bo-dists">
      <Distribution title={t("metrics.handoffs.byStatus")} rows={status} total={handoffs.total} />
      <Distribution title={t("metrics.handoffs.byPriority")} rows={priority} total={handoffs.total} />
      <Distribution title={t("metrics.handoffs.byDepartment")} rows={department} total={handoffs.total} />
      <Distribution title={t("metrics.handoffs.byOutcome")} rows={outcome} total={closed} />
    </div>
  );
}

export function MetricsReport({ data, now }: { data: MetricsResponse; now: number }) {
  const { t } = useI18n();
  const [open, setOpen] = useState<{ tools: boolean; cases: boolean }>({ tools: false, cases: false });
  const calls = data.tool_calls.reduce((total, row) => total + row.count, 0);
  return (
    <>
      <GlanceNumbers data={data} />
      <div className="bo-pair">
        <NotHelpfulList data={data} />
        <ToReviewList data={data} now={now} onOpenTools={() => setOpen({ ...open, tools: true })} />
      </div>
      <div className="pb-details">
        <div>
          <button type="button" className="pb-more" aria-expanded={open.tools} aria-controls="m-tools" onClick={() => setOpen({ ...open, tools: !open.tools })}>
            <Icon name="chev1" />
            {t("metrics.details.tools")} <span>· {t("metrics.details.toolsCount", { count: calls })}</span>
          </button>
          <div id="m-tools" hidden={!open.tools}>
            {data.tool_calls.length === 0 ? <p className="bo-empty">{t("metrics.empty")}</p> : <ToolCallsTable rows={data.tool_calls} />}
          </div>
        </div>
        <div>
          <button type="button" className="pb-more" aria-expanded={open.cases} aria-controls="m-cases" onClick={() => setOpen({ ...open, cases: !open.cases })}>
            <Icon name="chev1" />
            {t("metrics.details.cases")} <span>· {t("metrics.details.casesCount", { count: data.handoffs.total })}</span>
          </button>
          <div id="m-cases" hidden={!open.cases}>
            {data.handoffs.total === 0 ? <p className="bo-empty">{t("metrics.empty")}</p> : <HandoffTables handoffs={data.handoffs} />}
          </div>
        </div>
      </div>
    </>
  );
}

export function MetricsScreen() {
  const { t } = useI18n();
  const { api } = useAppServices();
  const [snapshot, send] = useMachine(metricsMachine, { input: { api } });
  const now = useNow(30000);
  const { data, error, hours } = snapshot.context;
  const loading = snapshot.matches("loading");

  return (
    <section className="bo-screen" aria-labelledby="metrics-title">
      <div className="bo-bar">
        <h1 className="h1" id="metrics-title">
          {t("metrics.title")}
        </h1>
        <div className="bo-toolbar">
          <div className="pb-tabs" role="radiogroup" aria-label={t("metrics.window")}>
            {METRICS_WINDOWS.map((value) => (
              <button key={value} type="button" className="pb-tab" role="radio" aria-checked={hours === value} onClick={() => send({ type: "WINDOW.SET", hours: value })}>
                {t(value === 24 ? "metrics.h24" : "metrics.h168")}
              </button>
            ))}
          </div>
          <span className="pb-t-small" role="status">
            {data ? `${t("metrics.updated", { time: clockText(data.generated_at) })} · ` : null}
            <button type="button" className="pb-btn pb-btn--ghost pb-btn--sm" disabled={loading} onClick={() => send({ type: "REFRESH" })}>
              <Icon name="retry" />
              {t("common.refresh")}
            </button>
          </span>
        </div>
      </div>

      {error !== null && (
        <Alert
          tone="caution"
          eyebrow={t("metrics.title")}
          action={
            <button type="button" className="pb-btn pb-btn--secondary pb-btn--sm" onClick={() => send({ type: "REFRESH" })}>
              {t("common.retry")}
            </button>
          }
        >
          {error === "unavailable" ? t("errors.unavailable") : t("metrics.loadFailed")}
        </Alert>
      )}

      {data === null ? loading && <p className="pb-t-small" role="status">{t("common.loading")}</p> : <MetricsReport data={data} now={now} />}
    </section>
  );
}
