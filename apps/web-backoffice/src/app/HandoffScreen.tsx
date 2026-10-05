// The case page (the declutter review of 2026-10-02): the case's reason as the title, its status on one
// line under it, the decisions top right (ADR-0018), then the summary card and the conversation side by
// side. Banners only for what the agent must act on: another agent holds the case, or the conversation
// did not open after the claim.

import type { HandoffDetail } from "@pattern-blue/contracts";
import { useMachine, useSelector } from "@xstate/react";
import { useCallback, useState, type ReactNode } from "react";
import type { ActorRefFrom, SnapshotFrom } from "xstate";
import type { DecisionResult } from "../machines/decision";
import { canClaim, handoffMachine, heldByAnother, heldByMe, selectSuggestion } from "../machines/handoff";
import { Composer, ComposerLocked, TranscriptLog } from "./Conversation";
import { useAppServices, useI18n, useLang, useNow, useVisibility } from "./context";
import { useDecisions } from "./Decisions";
import { clockText, waitText } from "./format";
import { HandoffCard } from "./HandoffCard";
import { Alert, CaseRef, Icon, PriorityChip } from "./ui";

type Snapshot = SnapshotFrom<typeof handoffMachine>;
type Send = ActorRefFrom<typeof handoffMachine>["send"];

export function CopyRef({ value }: { value: string }) {
  const { t } = useI18n();
  const [label, setLabel] = useState<"copy" | "copied" | "shown">("copy");
  const copy = () => {
    const done = () => {
      setLabel("copied");
      setTimeout(() => setLabel("copy"), 1400);
    };
    try {
      navigator.clipboard.writeText(value).then(done, () => setLabel("shown"));
    } catch {
      setLabel("shown");
    }
  };
  return (
    <button type="button" className="pb-btn pb-btn--ghost pb-btn--sm" onClick={copy}>
      {label === "copied" ? t("common.copied") : label === "shown" ? value : t("common.copy")}
    </button>
  );
}

/** The line under the title: priority, department, who holds the case, the wait, the id. */
export function CaseMeta({ detail, me, now }: { detail: HandoffDetail; me: string; now: number }) {
  const { t } = useI18n();
  const created = Date.parse(detail.created_at);
  const who =
    detail.status === "CLOSED" ? null : detail.assigned_agent === null ? (
      <span className="pb-casehead__sep">{detail.queue_position === null ? t("enums.status.QUEUED") : t("handoff.queued", { position: detail.queue_position })}</span>
    ) : detail.assigned_agent === me ? (
      <span className="pb-casehead__sep" data-me="">
        {t("handoff.yoursSince", { time: detail.assigned_at ? clockText(detail.assigned_at) : "" })}
      </span>
    ) : (
      <span className="pb-casehead__sep">{t("handoff.heldBy", { agent: detail.assigned_agent })}</span>
    );
  // The customer's wait ends when a person takes the case.
  const waited = detail.assigned_at ? t("handoff.waited", { time: waitText(created, Date.parse(detail.assigned_at)) }) : t("handoff.waiting", { time: waitText(created, now) });
  return (
    <p className="pb-casehead__meta">
      <PriorityChip priority={detail.priority} />
      <span>{t(`enums.department.${detail.department}`)}</span>
      {who}
      <span className="pb-casehead__sep">{waited}</span>
      <span className="pb-casehead__sep">
        <CaseRef value={detail.handoff_ref} large />
      </span>
      <CopyRef value={detail.handoff_ref} />
    </p>
  );
}

export function HandoffScreen({ handoffRef }: { handoffRef: string }) {
  const { t } = useI18n();
  const { api, actor } = useAppServices();
  const me = useSelector(actor, (snapshot) => snapshot.context.agent) ?? "";
  const [snapshot, send] = useMachine(handoffMachine, { input: { api, ref: handoffRef, agentRef: me } });
  useVisibility(send);
  const now = useNow(1000);
  const { context } = snapshot;

  const back = (
    <a className="pb-btn pb-btn--ghost pb-btn--sm bo-back" href="#/">
      <i className="pb-ico pb-ico--arrow pb-ico--flip" aria-hidden="true" />
      {t("handoff.back")}
    </a>
  );

  if (context.detail === null) {
    return (
      <section className="bo-screen" aria-labelledby="case-title">
        {back}
        <h1 className="h1" id="case-title">
          {t("handoff.title")}
        </h1>
        {snapshot.matches({ detail: "loading" }) ? (
          <p className="pb-t-small" role="status">
            {t("common.loading")}
          </p>
        ) : (
          <Alert
            tone="caution"
            eyebrow={t("handoff.title")}
            action={
              context.detailError === "notFound" ? undefined : (
                <button type="button" className="pb-btn pb-btn--secondary pb-btn--sm" onClick={() => send({ type: "RETRY" })}>
                  {t("common.retry")}
                </button>
              )
            }
          >
            {context.detailError === "notFound" ? t("handoff.notFound") : context.detailError === "unavailable" ? t("errors.unavailable") : t("handoff.loadFailed")}
          </Alert>
        )}
      </section>
    );
  }

  return <CasePage detail={context.detail} snapshot={snapshot} send={send} me={me} now={now} back={back} />;
}

function CasePage({ detail, snapshot, send, me, now, back }: { detail: HandoffDetail; snapshot: Snapshot; send: Send; me: string; now: number; back: ReactNode }) {
  const { t } = useI18n();
  const lang = useLang();
  const { context } = snapshot;
  const claiming = snapshot.matches({ claim: "claiming" });
  const mine = heldByMe(context);
  const other = heldByAnother(context) || context.claimError === "heldByAnother";
  const claimError = context.claimError;
  const takeable = canClaim(context);

  const onDecided = useCallback(
    (_result: DecisionResult) => {
      send({ type: "DETAIL.RELOAD" });
      send({ type: "TRANSCRIPT.REFRESH" });
    },
    [send],
  );
  const decisions = useDecisions({ detail, me, conversationAlive: context.conversationId !== null, messageLang: context.language ?? lang, onDone: onDecided });

  const take = () => send({ type: "CLAIM" });
  const takeLabel = claiming ? t("handoff.taking") : claimError !== null ? t("handoff.retryTake") : t("handoff.take");

  const live = snapshot.matches({ transcript: { ready: "live" } });
  const paused = snapshot.matches({ transcript: { ready: { live: "paused" } } });

  return (
    <section className="bo-screen" aria-labelledby="case-title">
      {back}
      <header className="pb-casehead">
        <h1 className="h1" id="case-title">
          {t(`enums.reason.${detail.reason}`)}
        </h1>
        <div className="pb-casehead__bar">
          {takeable && decisions.idle && (
            <button type="button" className="pb-btn pb-btn--primary pb-btn--sm" disabled={claiming} onClick={take}>
              <Icon name="handoff" />
              {takeLabel}
            </button>
          )}
          {decisions.buttons}
        </div>
        <CaseMeta detail={detail} me={me} now={now} />
        {decisions.panel}
      </header>

      <div className="bo-notices">
        {other && !mine && detail.status !== "CLOSED" && (
          <Alert tone="caution" eyebrow={t("handoff.heldByOtherEyebrow")}>
            {t("handoff.heldByOther", { agent: detail.assigned_agent ?? context.takeover?.agent_ref ?? t("common.unknown") })}
          </Alert>
        )}
        {claimError === "claimedButTakeoverFailed" && !mine && (
          <Alert
            tone="caution"
            stripe
            eyebrow={t("handoff.takeoverFailedEyebrow")}
            hint={t("handoff.takeoverFailedHint")}
            action={
              <button type="button" className="pb-btn pb-btn--secondary pb-btn--sm" disabled={claiming} onClick={take}>
                {t("common.retry")}
              </button>
            }
          >
            {t("handoff.takeoverFailedText")}
          </Alert>
        )}
        {(claimError === "unavailable" || claimError === "other" || claimError === "notFound" || claimError === "unauthorized") && (
          <Alert tone="caution" eyebrow={t("handoff.take")}>
            {claimError === "unavailable" ? t("errors.unavailable") : claimError === "notFound" ? t("handoff.notFound") : t("errors.generic")}
          </Alert>
        )}
      </div>

      <div className="bo-split">
        <HandoffCard detail={detail} />

        <section className="pb-cut pb-convo" aria-labelledby="conversation-title">
          <div className="pb-convo__head">
            <h2 className="pb-chat__title" id="conversation-title">
              {t("handoff.transcript.title")}
            </h2>
            <span className="pb-live" data-paused={live && !paused ? undefined : ""} role="status">
              {live && !paused ? t("handoff.transcript.live") : paused ? t("handoff.transcript.paused") : t("handoff.transcript.snapshot")}
            </span>
          </div>

          {context.conversationId === null ? (
            <div className="pb-empty">
              <b>{t("handoff.transcript.none")}</b>
              <span>{t("handoff.transcript.noneHint")}</span>
            </div>
          ) : snapshot.matches({ transcript: "failed" }) ? (
            <div className="bo-panel-note">
              <Alert
                tone="caution"
                eyebrow={t("handoff.transcript.title")}
                action={
                  <button type="button" className="pb-btn pb-btn--secondary pb-btn--sm" onClick={() => send({ type: "TRANSCRIPT.RETRY" })}>
                    {t("common.retry")}
                  </button>
                }
              >
                {context.transcriptError === "unavailable" ? t("errors.unavailable") : t("handoff.transcript.failed")}
              </Alert>
            </div>
          ) : snapshot.matches({ transcript: "loading" }) || snapshot.matches({ transcript: "none" }) ? (
            <p className="pb-t-small bo-panel-note" role="status">
              {t("common.loading")}
            </p>
          ) : (
            <>
              <TranscriptLog messages={context.messages} me={me} holder={context.takeover?.active ? (context.takeover.agent_ref ?? null) : null} />
              {mine ? (
                <Composer
                  sending={snapshot.matches({ composer: "sending" })}
                  failed={snapshot.matches({ composer: "failed" })}
                  outbox={context.outbox}
                  error={context.sendError}
                  suggestion={selectSuggestion(snapshot)}
                  onSend={(text) => send({ type: "SEND", text })}
                  onRetry={() => send({ type: "SEND.RETRY" })}
                  onDiscard={() => send({ type: "SEND.DISCARD" })}
                />
              ) : (
                <ComposerLocked reason={other ? "other" : "take"} onTake={takeable ? take : undefined} taking={claiming} />
              )}
            </>
          )}
        </section>
      </div>
    </section>
  );
}
