import { useMachine } from "@xstate/react";
import { queueMachine, type QueueFilter } from "../machines/queue";
import { useAppServices, useI18n, useNow, useVisibility } from "./context";
import { clockText } from "./format";
import { QueueTable } from "./QueueRow";
import { Alert } from "./ui";

const FILTERS: readonly QueueFilter[] = ["OPEN", "QUEUED", "ASSIGNED"];

export function QueueScreen() {
  const { t } = useI18n();
  const { api } = useAppServices();
  const [snapshot, send] = useMachine(queueMachine, { input: { api } });
  useVisibility(send);
  const now = useNow(1000);
  const { items, loaded, error, updatedAt, filter } = snapshot.context;
  const paused = snapshot.matches("paused");

  const filterWord = (value: QueueFilter) => (value === "OPEN" ? t("queue.filterAll") : t(`enums.status.${value}`));

  return (
    <section aria-labelledby="queue-title" className="bo-screen">
      <div className="bo-bar">
        <h1 className="h1" id="queue-title">
          {t("queue.title")}
        </h1>
        <span className="pb-t-small" role="status">
          {[items.length === 1 ? t("queue.summaryOne") : t("queue.summary", { count: items.length }), paused ? t("queue.paused") : t("queue.live")].join(" · ")}
          {updatedAt !== null ? ` · ${t("common.updatedAt", { time: clockText(new Date(updatedAt).toISOString()) })}` : ""}
        </span>
      </div>

      <fieldset className="pb-modes bo-filter" role="radiogroup">
        <legend>{t("queue.filterLabel")}</legend>
        {FILTERS.map((value) => (
          <button
            key={value}
            type="button"
            className="pb-btn pb-btn--sm"
            role="radio"
            aria-checked={filter === value}
            onClick={() => send({ type: "FILTER.SET", filter: value })}
          >
            {filterWord(value)}
            {value !== "OPEN" && <span className="bo-raw"> ({value})</span>}
          </button>
        ))}
      </fieldset>

      {error !== null && (
        <Alert
          tone="caution"
          eyebrow={t("queue.title")}
          action={
            <button type="button" className="pb-btn pb-btn--secondary pb-btn--sm" onClick={() => send({ type: "REFRESH" })}>
              {t("common.retry")}
            </button>
          }
        >
          {error === "unavailable" ? t("errors.unavailable") : t("errors.generic")}
        </Alert>
      )}

      {!loaded ? (
        <p className="pb-t-small" role="status">
          {t("common.loading")}
        </p>
      ) : items.length === 0 ? (
        <p className="bo-empty" role="status">
          {t("queue.empty")}
        </p>
      ) : (
        <QueueTable items={items} now={now} />
      )}
    </section>
  );
}
