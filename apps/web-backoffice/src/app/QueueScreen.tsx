// The queue: the open cases, refreshed every 3 s, with four tabs an agent asks for (all, nobody's, mine,
// someone else's) and a summary under each row. The tabs filter the list the machine already loads, by
// status and by the agent signed in, so they need nothing more from the API.

import type { HandoffItem } from "@pattern-blue/contracts";
import { useSelector } from "@xstate/react";
import { useMachine } from "@xstate/react";
import { useCallback, useEffect, useState } from "react";
import type { DecisionResult } from "../machines/decision";
import { queueMachine } from "../machines/queue";
import { useAppServices, useI18n, useNow, useVisibility } from "./context";
import { QueueTable } from "./QueueRow";
import { Alert } from "./ui";

export type QueueTab = "all" | "unclaimed" | "mine" | "others";
const TABS: readonly QueueTab[] = ["all", "unclaimed", "mine", "others"];

export function inTab(tab: QueueTab, item: HandoffItem, me: string): boolean {
  if (tab === "unclaimed") return item.assigned_agent === null;
  if (tab === "mine") return item.assigned_agent === me;
  if (tab === "others") return item.assigned_agent !== null && item.assigned_agent !== me;
  return true;
}

/** How long a case decided here stays in the list after the refresh that drops it. */
const DECIDED_KEEP_MS = 8000;

export function QueueScreen() {
  const { t } = useI18n();
  const { api, actor } = useAppServices();
  const me = useSelector(actor, (snapshot) => snapshot.context.agent) ?? "";
  const [snapshot, send] = useMachine(queueMachine, { input: { api } });
  useVisibility(send);
  const now = useNow(1000);
  const { items, loaded, error } = snapshot.context;
  const paused = snapshot.matches("paused");

  const [tab, setTab] = useState<QueueTab>("all");
  const [open, setOpen] = useState<{ ref: string; pinned: boolean } | null>(null);
  // Cases decided here: kept on screen, dimmed, for a few seconds after the refresh drops them.
  const [decided, setDecided] = useState<Map<string, { item: HandoffItem; index: number; until: number }>>(new Map());

  const onOpen = useCallback((ref: string, pin: boolean) => setOpen((current) => ({ ref, pinned: pin || (current?.ref === ref && current.pinned) })), []);
  const onClose = useCallback((ref: string) => setOpen((current) => (current?.ref === ref ? null : current)), []);
  const onDecided = useCallback(
    (item: HandoffItem, result: DecisionResult) => {
      setDecided((current) => {
        const next = new Map(current);
        next.set(item.handoff_ref, { item: { ...item, ...result.handoff }, index: items.findIndex((candidate) => candidate.handoff_ref === item.handoff_ref), until: Date.now() + DECIDED_KEEP_MS });
        return next;
      });
      send({ type: "REFRESH" });
    },
    [items, send],
  );

  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(null);
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, []);

  // The list on screen: the machine's, plus the cases decided here that it no longer has.
  const recent = new Set([...decided].filter(([, kept]) => kept.until >= now).map(([ref]) => ref));
  const shown = [...items];
  for (const [ref, kept] of decided) {
    if (!recent.has(ref) || shown.some((item) => item.handoff_ref === ref)) continue;
    shown.splice(Math.max(0, Math.min(kept.index, shown.length)), 0, kept.item);
  }
  const counts = Object.fromEntries(TABS.map((name) => [name, items.filter((item) => inTab(name, item, me)).length])) as Record<QueueTab, number>;
  const visible = shown.filter((item) => recent.has(item.handoff_ref) || inTab(tab, item, me));

  return (
    <section aria-labelledby="queue-title" className="bo-screen">
      <div className="bo-bar">
        <h1 className="h1" id="queue-title">
          {t("queue.title")}
        </h1>
        <span className="pb-live" data-paused={paused ? "" : undefined} role="status">
          {paused ? t("queue.paused") : t("queue.live")}
        </span>
      </div>

      <div className="pb-tabs" role="radiogroup" aria-label={t("queue.tabsLabel")}>
        {TABS.map((name) => (
          <button key={name} type="button" className="pb-tab" role="radio" aria-checked={tab === name} onClick={() => setTab(name)}>
            {t(`queue.tab.${name}`)} <b>{counts[name]}</b>
          </button>
        ))}
      </div>

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
      ) : visible.length === 0 ? (
        <p className="bo-empty" role="status">
          {t("queue.empty")}
        </p>
      ) : (
        <QueueTable
          items={visible}
          now={now}
          me={me}
          openRef={open?.ref ?? null}
          pinned={open?.pinned ?? false}
          decided={recent}
          onOpen={onOpen}
          onClose={onClose}
          onDecided={onDecided}
        />
      )}
    </section>
  );
}
