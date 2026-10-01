// Metrics: what banking-core aggregates from ops.audit_log and ops.handoff over a window. Only what the
// endpoint returns is shown (tool calls, handoffs, cards blocked, OTP counts). No rates or averages are
// derived here, and there are no decision-point numbers: nothing in the admin API feeds them.

import { DepartmentSchema, HANDOFF_PRIORITY_ORDER, HandoffStatusSchema, type MetricsResponse } from "@pattern-blue/contracts";
import { useMachine } from "@xstate/react";
import type { CSSProperties } from "react";
import { METRICS_WINDOWS, metricsMachine } from "../machines/metrics";
import { useAppServices, useI18n } from "./context";
import { dateTimeText, percent } from "./format";
import { Alert, DecisionChip } from "./ui";

const DECISION_ORDER = { allowed: 0, refused: 1, error: 2 } as const;
const DECISION_GAUGE = { allowed: "decided", refused: "caution", error: "blocked" } as const;

type ToolCall = MetricsResponse["tool_calls"][number];

export function ToolCallsTable({ rows }: { rows: readonly ToolCall[] }) {
  const { t } = useI18n();
  const total = rows.reduce((sum, row) => sum + row.count, 0);
  const sorted = [...rows].sort((a, b) => a.action.localeCompare(b.action) || DECISION_ORDER[a.decision] - DECISION_ORDER[b.decision]);

  return (
    <div className="pb-queue bo-table bo-cols-tools" role="table" aria-label={t("metrics.tools.title")}>
      <div className="pb-queue__head" role="row">
        <span role="columnheader">{t("metrics.tools.action")}</span>
        <span role="columnheader">{t("metrics.tools.decision")}</span>
        <span role="columnheader">{t("metrics.tools.reason")}</span>
        <span role="columnheader">{t("metrics.tools.count")}</span>
        <span role="columnheader">{t("metrics.tools.share")}</span>
      </div>
      {sorted.map((row, index) => {
        const share = percent(row.count, total);
        return (
          <div className="pb-qrow" role="row" key={`${row.action}-${row.decision}-${row.reason_code ?? ""}-${index}`}>
            <span role="cell" data-col="name">
              {row.action}
            </span>
            <span role="cell" data-col="decision">
              <span className="bo-cell">
                <DecisionChip decision={row.decision} />
                <span className="pb-t-small">{t(`enums.decision.${row.decision}`)}</span>
              </span>
            </span>
            <span role="cell" data-col="reason">
              {row.reason_code === null ? (
                <span className="pb-t-small">{t("common.empty")}</span>
              ) : (
                <span className="bo-cell">
                  <span className="pb-t-small">{row.reason_code in REASON_KEYS ? t(REASON_KEYS[row.reason_code as keyof typeof REASON_KEYS]) : ""}</span>
                  <span>{row.reason_code}</span>
                </span>
              )}
            </span>
            <span role="cell" data-col="count">
              {row.count}
            </span>
            <span role="cell" data-col="share">
              <span className="bo-share">
                <span
                  className="pb-gauge pb-gauge--sm"
                  data-state={DECISION_GAUGE[row.decision]}
                  style={{ "--n": 20, "--on": row.count > 0 ? Math.max(1, Math.round((row.count / Math.max(total, 1)) * 20)) : 0 } as CSSProperties}
                  role="meter"
                  aria-valuemin={0}
                  aria-valuemax={total}
                  aria-valuenow={row.count}
                  aria-valuetext={t("metrics.tools.meter", { action: row.action, decision: row.decision, count: row.count, total })}
                >
                  <span className="pb-gauge__track">
                    <span className="pb-gauge__fill" />
                  </span>
                </span>
                <span>{share}%</span>
              </span>
            </span>
          </div>
        );
      })}
    </div>
  );
}

const REASON_KEYS = {
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

/** One distribution: every value of the enum with its word, the raw enum and its count (0 when the API leaves it out). */
function Distribution({ title, rows, total }: { title: string; rows: { raw: string; word: string; count: number }[]; total: number }) {
  const { t } = useI18n();
  return (
    <div className="bo-dist">
      <h3 className="h3">{title}</h3>
      <div className="pb-queue bo-table bo-cols-dist" role="table" aria-label={title}>
        <div className="pb-queue__head" role="row">
          <span role="columnheader">{t("metrics.handoffs.value")}</span>
          <span role="columnheader">{t("metrics.handoffs.count")}</span>
          <span role="columnheader">{t("metrics.handoffs.share")}</span>
        </div>
        {rows.map((row) => (
          <div className="pb-qrow" role="row" key={row.raw}>
            <span role="cell" data-col="name">
              <span className="bo-cell">
                <span className="pb-t-small">{row.word}</span>
                <span>{row.raw}</span>
              </span>
            </span>
            <span role="cell" data-col="count">
              {row.count}
            </span>
            <span role="cell" data-col="share">
              {percent(row.count, total)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function HandoffTables({ handoffs }: { handoffs: MetricsResponse["handoffs"] }) {
  const { t } = useI18n();
  const status = HandoffStatusSchema.options.map((raw) => ({ raw, word: t(`enums.status.${raw}`), count: handoffs.by_status[raw] ?? 0 }));
  const priority = HANDOFF_PRIORITY_ORDER.map((raw) => ({ raw, word: t(`enums.priority.${raw}`), count: handoffs.by_priority[raw] ?? 0 }));
  const department = DepartmentSchema.options.map((raw) => ({ raw, word: t(`enums.department.${raw}`), count: handoffs.by_department[raw] ?? 0 }));
  return (
    <div className="bo-dists">
      <Distribution title={t("metrics.handoffs.byStatus")} rows={status} total={handoffs.total} />
      <Distribution title={t("metrics.handoffs.byPriority")} rows={priority} total={handoffs.total} />
      <Distribution title={t("metrics.handoffs.byDepartment")} rows={department} total={handoffs.total} />
    </div>
  );
}

function Stat({ label, value, hideLabel = false }: { label: string; value: number; hideLabel?: boolean }) {
  return (
    <div className="bo-stat">
      <span className={hideLabel ? "pb-sr" : "pb-t-label"}>{label}</span>
      <span className="pb-t-code">{value}</span>
    </div>
  );
}

export function MetricsReport({ data }: { data: MetricsResponse }) {
  const { t } = useI18n();
  return (
    <>
      <section className="bo-section" aria-labelledby="m-tools">
        <h2 className="h2" id="m-tools">
          {t("metrics.tools.title")}
        </h2>
        <p className="pb-t-small">{t("metrics.tools.help")}</p>
        {data.tool_calls.length === 0 ? <p className="bo-empty">{t("metrics.empty")}</p> : <ToolCallsTable rows={data.tool_calls} />}
      </section>

      <section className="bo-section" aria-labelledby="m-handoffs">
        <h2 className="h2" id="m-handoffs">
          {t("metrics.handoffs.title")}
        </h2>
        <p className="pb-t-small">{t("metrics.handoffs.total", { total: data.handoffs.total })}</p>
        {data.handoffs.total === 0 ? <p className="bo-empty">{t("metrics.empty")}</p> : <HandoffTables handoffs={data.handoffs} />}
      </section>

      <div className="bo-tiles">
        <section className="pb-card bo-tile" aria-labelledby="m-cards">
          <h2 className="pb-t-h3" id="m-cards">
            {t("metrics.cards.title")}
          </h2>
          <p className="pb-t-small">{t("metrics.cards.help")}</p>
          <Stat label={t("metrics.cards.title")} value={data.cards_blocked} hideLabel />
        </section>
        <section className="pb-card bo-tile" aria-labelledby="m-otp">
          <h2 className="pb-t-h3" id="m-otp">
            {t("metrics.otp.title")}
          </h2>
          <div className="bo-stats">
            <Stat label={t("metrics.otp.sent")} value={data.otp.sent} />
            <Stat label={t("metrics.otp.verified")} value={data.otp.verified} />
            <Stat label={t("metrics.otp.failed")} value={data.otp.failed} />
          </div>
        </section>
      </div>
    </>
  );
}

export function MetricsScreen() {
  const { t } = useI18n();
  const { api } = useAppServices();
  const [snapshot, send] = useMachine(metricsMachine, { input: { api } });
  const { data, error, hours } = snapshot.context;
  const loading = snapshot.matches("loading");

  return (
    <section className="bo-screen" aria-labelledby="metrics-title">
      <div className="bo-bar">
        <h1 className="h1" id="metrics-title">
          {t("metrics.title")}
        </h1>
        <span className="pb-t-small" role="status">
          {data ? t("metrics.generated", { time: dateTimeText(data.generated_at), hours: data.window_hours }) : null}
        </span>
      </div>

      <div className="bo-toolbar">
        <fieldset className="pb-modes bo-filter" role="radiogroup">
          <legend>{t("metrics.window")}</legend>
          {METRICS_WINDOWS.map((value) => (
            <button key={value} type="button" className="pb-btn pb-btn--sm" role="radio" aria-checked={hours === value} onClick={() => send({ type: "WINDOW.SET", hours: value })}>
              {t(value === 24 ? "metrics.h24" : "metrics.h168")}
            </button>
          ))}
        </fieldset>
        <button type="button" className="pb-btn pb-btn--ghost pb-btn--sm" disabled={loading} onClick={() => send({ type: "REFRESH" })}>
          {t("common.refresh")}
        </button>
        <span className="pb-t-small">{t("metrics.source")}</span>
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

      {data === null ? (
        loading && <p className="pb-t-small" role="status">{t("common.loading")}</p>
      ) : (
        <MetricsReport data={data} />
      )}
    </section>
  );
}
