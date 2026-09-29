import { useSelector } from "@xstate/react";
import { useMachine } from "@xstate/react";
import { canClaim, handoffMachine, heldByAnother, heldByMe } from "../machines/handoff";
import { agentName, Composer, TranscriptLog } from "./Conversation";
import { useAppServices, useI18n, useNow, useVisibility } from "./context";
import { HandoffCard } from "./HandoffCard";
import { Alert, Icon } from "./ui";

export function HandoffScreen({ handoffRef }: { handoffRef: string }) {
  const { t } = useI18n();
  const { api, actor } = useAppServices();
  const me = useSelector(actor, (snapshot) => snapshot.context.agent) ?? "";
  const [snapshot, send] = useMachine(handoffMachine, { input: { api, ref: handoffRef, agentRef: me } });
  useVisibility(send);
  const now = useNow(1000);
  const { context } = snapshot;

  const claiming = snapshot.matches({ claim: "claiming" });
  const mine = heldByMe(context);
  const other = heldByAnother(context) || context.claimError === "heldByAnother";

  const back = (
    <a className="pb-link bo-back" href="#/">
      {t("handoff.back")}
    </a>
  );

  if (snapshot.matches({ detail: "loading" })) {
    return (
      <section className="bo-screen" aria-labelledby="case-title">
        {back}
        <h1 className="h1" id="case-title">
          {t("handoff.title")}
        </h1>
        <p className="pb-t-small" role="status">
          {t("common.loading")}
        </p>
      </section>
    );
  }

  if (context.detail === null) {
    return (
      <section className="bo-screen" aria-labelledby="case-title">
        {back}
        <h1 className="h1" id="case-title">
          {t("handoff.title")}
        </h1>
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
      </section>
    );
  }

  const claimLabel = claiming ? t("handoff.taking") : context.claimError !== null || context.detail.assigned_agent === me ? t("handoff.retryTake") : t("handoff.take");
  const actions = canClaim(context) ? (
    <button type="button" className="pb-btn pb-btn--primary pb-btn--sm" disabled={claiming} onClick={() => send({ type: "CLAIM" })}>
      <Icon name="handoff" />
      {claimLabel}
    </button>
  ) : undefined;

  const claimError = context.claimError;

  return (
    <section className="bo-screen" aria-labelledby="case-title">
      {back}
      <h1 className="h1" id="case-title">
        {t("handoff.title")}
      </h1>

      <div className="bo-notices">
        {other && !mine && (
          <Alert tone="caution" eyebrow={t("enums.status.ASSIGNED")} hint={t("handoff.heldByOtherHint")}>
            {t("handoff.heldByOther")}
          </Alert>
        )}
        {claimError === "claimedButTakeoverFailed" && !mine && (
          <Alert tone="caution" stripe eyebrow={t("handoff.takeoverFailedEyebrow")} hint={t("handoff.takeoverFailedHint")}>
            {t("handoff.takeoverFailedText")}
          </Alert>
        )}
        {(claimError === "unavailable" || claimError === "other" || claimError === "notFound" || claimError === "unauthorized") && (
          <Alert tone="caution" eyebrow={t("handoff.take")}>
            {claimError === "unavailable" ? t("errors.unavailable") : claimError === "notFound" ? t("handoff.notFound") : t("errors.generic")}
          </Alert>
        )}
        {mine && (
          <Alert tone="success" eyebrow={t("handoff.takenEyebrow")}>
            {t("handoff.takenText")}
          </Alert>
        )}
      </div>

      <div className="bo-split">
        <HandoffCard detail={context.detail} now={now} me={me} actions={actions} />

        <section className="pb-chat bo-chat" aria-labelledby="conversation-title">
          <div className="pb-chat__head">
            <h2 className="pb-chat__title" id="conversation-title">
              {t("handoff.transcript.title")}
            </h2>
            <span className="pb-t-small" role="status">
              {snapshot.matches({ transcript: { ready: { live: "paused" } } })
                ? t("handoff.transcript.paused")
                : snapshot.matches({ transcript: { ready: "live" } })
                  ? t("handoff.transcript.live")
                  : t("handoff.transcript.masked")}
            </span>
          </div>

          {context.conversationId === null ? (
            <div className="bo-panel-note">
              <Alert tone="info" eyebrow={t("handoff.transcript.title")}>
                {t("handoff.transcript.none")}
              </Alert>
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
              <TranscriptLog messages={context.messages} agent={agentName(context.takeover?.agent_ref ?? null)} />
              {!mine && <p className="pb-t-small bo-panel-note">{t("handoff.transcript.snapshot")}</p>}
              <Composer
                enabled={mine}
                lockedReason={other ? "lockedOther" : "locked"}
                sending={snapshot.matches({ composer: "sending" })}
                failed={snapshot.matches({ composer: "failed" })}
                outbox={context.outbox}
                error={context.sendError}
                onSend={(text) => send({ type: "SEND", text })}
                onRetry={() => send({ type: "SEND.RETRY" })}
                onDiscard={() => send({ type: "SEND.DISCARD" })}
              />
            </>
          )}
        </section>
      </div>
    </section>
  );
}
