// The handoff queue, lean (the declutter review of 2026-10-02): priority first, then the case in words
// (reason, department, disputed amount and the id in mono), who holds it, the wait, and a chevron that
// opens the case's summary under the row. The row's title is its link, so the whole row opens the case.
//
// The summary reads the case detail on first open and offers the decisions banking-core allows
// (ADR-0018). It opens on hover after 300 ms, at once when the chevron gets focus, and stays open when
// the chevron is pressed; Escape closes it (QueueScreen).

import type { BackofficeHandoffDetail, HandoffItem } from "@pattern-blue/contracts";
import { useEffect, useRef, useState } from "react";
import type { DecisionResult } from "../machines/decision";
import { categorize, type ErrorCategory } from "../api/errors";
import { ChargeBlock, disputedCharge, IdentityFact, PolicyFacts, SaidQuotes, WriteFacts } from "./CaseFacts";
import { useAppServices, useI18n, useLang } from "./context";
import { useDecisions } from "./Decisions";
import { money, waitText } from "./format";
import { CaseRef, Icon, PriorityChip } from "./ui";

export const HOVER_OPEN_MS = 300;
const HOVER_CLOSE_MS = 200;

export interface QueueRowProps {
  item: HandoffItem;
  now: number;
  /** The agent signed in. */
  me: string;
  open: boolean;
  /** Opened with the chevron (or by acting in it): leaving the row does not close it. */
  pinned: boolean;
  /** Open the summary above the row instead of below: the last rows of a long list. */
  up: boolean;
  /** The case was just decided: the row stays, dimmed, until the next refresh drops it. */
  decided: boolean;
  onOpen: (ref: string, pin: boolean) => void;
  onClose: (ref: string) => void;
  onDecided: (item: HandoffItem, result: DecisionResult) => void;
}

/** "En cola · 2.º", "Tú" or the agent who holds the case. */
function Who({ item, me }: { item: HandoffItem; me: string }) {
  const { t } = useI18n();
  if (item.status === "CLOSED") return <span className="pb-who">{t(`enums.status.${item.status}`)}</span>;
  if (item.assigned_agent === null) {
    return <span className="pb-who">{item.queue_position === null ? t("enums.status.QUEUED") : t("queue.waiting", { position: item.queue_position })}</span>;
  }
  if (item.assigned_agent === me) {
    return (
      <span className="pb-who" data-me="">
        <Icon name="user" />
        {t("queue.you")}
      </span>
    );
  }
  return (
    <span className="pb-who" data-other="">
      <Icon name="user" />
      {item.assigned_agent}
    </span>
  );
}

export function QueueRow({ item, now, me, open, pinned, up, decided, onOpen, onClose, onDecided }: QueueRowProps) {
  const { t } = useI18n();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clear = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };
  useEffect(() => clear, []);
  const peekId = `peek-${item.handoff_ref}`;

  return (
    <div
      className="pb-crow"
      role="row"
      data-open={open ? "" : undefined}
      data-closed={decided ? "" : undefined}
      onMouseEnter={() => {
        clear();
        if (!open) timer.current = setTimeout(() => onOpen(item.handoff_ref, false), HOVER_OPEN_MS);
      }}
      onMouseLeave={() => {
        clear();
        if (open && !pinned) timer.current = setTimeout(() => onClose(item.handoff_ref), HOVER_CLOSE_MS);
      }}
    >
      <span role="cell" data-col="pri">
        <PriorityChip priority={item.priority} />
      </span>
      <span role="cell" data-col="case" className="pb-crow__case">
        <a className="pb-crow__title" href={`#/handoffs/${item.handoff_ref}`} aria-label={t("queue.openCase", { ref: item.handoff_ref })}>
          {t(`enums.reason.${item.reason}`)}
        </a>
        <span className="pb-crow__sub">
          <span>{t(`enums.department.${item.department}`)}</span>
          {item.disputed_amount && <span className="pb-crow__amount">{money(item.disputed_amount.amount_minor, item.disputed_amount.currency)}</span>}
          <CaseRef value={item.handoff_ref} />
        </span>
      </span>
      <span role="cell" data-col="who">
        <Who item={item} me={me} />
      </span>
      <span role="cell" data-col="wait" className="pb-wait">
        {waitText(Date.parse(item.created_at), now)}
      </span>
      <span role="cell" data-col="peek">
        <button
          type="button"
          className="pb-peekbtn"
          aria-expanded={open}
          aria-controls={peekId}
          aria-label={t("queue.summary")}
          onFocus={() => {
            clear();
            if (!open) onOpen(item.handoff_ref, false);
          }}
          onClick={() => (open && pinned ? onClose(item.handoff_ref) : onOpen(item.handoff_ref, true))}
        >
          <Icon name="chev1" />
        </button>
      </span>
      {open && (
        <QueueSummary
          id={peekId}
          item={item}
          me={me}
          up={up}
          onPin={() => onOpen(item.handoff_ref, true)}
          onDecided={(result) => onDecided(item, result)}
        />
      )}
    </div>
  );
}

/** The case detail for the summary, read once when it opens. */
function useCaseDetail(ref: string): { detail: BackofficeHandoffDetail | null; error: ErrorCategory | null } {
  const { api } = useAppServices();
  const [state, setState] = useState<{ detail: BackofficeHandoffDetail | null; error: ErrorCategory | null }>({ detail: null, error: null });
  useEffect(() => {
    let live = true;
    api.getHandoff(ref).then(
      (detail) => live && setState({ detail, error: null }),
      (error: unknown) => live && setState({ detail: null, error: categorize(error) }),
    );
    return () => {
      live = false;
    };
  }, [api, ref]);
  return state;
}

export function QueueSummary({
  id,
  item,
  me,
  up,
  onPin,
  onDecided,
}: {
  id: string;
  item: HandoffItem;
  me: string;
  up: boolean;
  onPin: () => void;
  onDecided: (result: DecisionResult) => void;
}) {
  const { t } = useI18n();
  const { detail, error } = useCaseDetail(item.handoff_ref);
  return (
    // Acting inside the summary keeps it open when the pointer leaves the row.
    <div className="pb-cut pb-peek" id={id} role="region" aria-label={t("queue.summaryOf", { reason: t(`enums.reason.${item.reason}`) })} data-up={up ? "" : undefined} onPointerDown={onPin}>
      <div className="pb-peek__head">
        <p className="pb-peek__title">
          {t(`enums.reason.${item.reason}`)}
          <small>{t(`enums.department.${item.department}`)}</small>
        </p>
        <PriorityChip priority={item.priority} />
      </div>
      {detail ? (
        <SummaryBody detail={detail} me={me} onDecided={onDecided} />
      ) : error ? (
        <p className="pb-decide__note" role="alert">
          <Icon name="warning" />
          {error === "unavailable" ? t("errors.unavailable") : t("queue.summaryFailed")}
        </p>
      ) : (
        <p className="pb-decide__note" role="status">
          {t("common.loading")}
        </p>
      )}
    </div>
  );
}

function SummaryBody({ detail, me, onDecided }: { detail: BackofficeHandoffDetail; me: string; onDecided: (result: DecisionResult) => void }) {
  const { t } = useI18n();
  const lang = useLang();
  const charge = disputedCharge(detail.summary);
  const decisions = useDecisions({ detail, me, conversationAlive: detail.conversation_id !== null, messageLang: lang, onDone: onDecided });
  return (
    <>
      {charge && <ChargeBlock charge={charge} />}
      <ul className="pb-facts">
        <IdentityFact summary={detail.summary} />
        <WriteFacts summary={detail.summary} />
        <PolicyFacts summary={detail.summary} />
      </ul>
      <SaidQuotes summary={detail.summary} />
      {decisions.idle && (
        <div className="pb-decide">
          {decisions.buttons}
          <a className="pb-action" href={`#/handoffs/${detail.handoff_ref}`}>
            {t("queue.open")}
            <Icon name="arrow" />
          </a>
        </div>
      )}
      {decisions.panel}
    </>
  );
}

export function QueueTable({
  items,
  now,
  me,
  openRef,
  pinned,
  decided,
  onOpen,
  onClose,
  onDecided,
}: {
  items: readonly HandoffItem[];
  now: number;
  me: string;
  openRef: string | null;
  pinned: boolean;
  /** Cases decided here that the next refresh will drop. */
  decided: ReadonlySet<string>;
  onOpen: (ref: string, pin: boolean) => void;
  onClose: (ref: string) => void;
  onDecided: (item: HandoffItem, result: DecisionResult) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="pb-cases" role="table" aria-label={t("queue.tableLabel")}>
      <div className="pb-cases__head" role="row">
        <span role="columnheader">{t("queue.col.priority")}</span>
        <span role="columnheader">{t("queue.col.case")}</span>
        <span role="columnheader">{t("queue.col.who")}</span>
        <span role="columnheader" data-col="wait">
          {t("queue.col.wait")}
        </span>
        <span role="columnheader">
          <span className="pb-sr">{t("queue.summary")}</span>
        </span>
      </div>
      {items.map((item, index) => (
        <QueueRow
          key={item.handoff_ref}
          item={item}
          now={now}
          me={me}
          open={openRef === item.handoff_ref}
          pinned={openRef === item.handoff_ref && pinned}
          up={items.length > 3 && index >= items.length - 2}
          decided={decided.has(item.handoff_ref)}
          onOpen={onOpen}
          onClose={onClose}
          onDecided={onDecided}
        />
      ))}
    </div>
  );
}
