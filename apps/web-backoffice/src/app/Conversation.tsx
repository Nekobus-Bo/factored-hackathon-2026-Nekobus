// The agent's view of a conversation: the masked transcript in the design system's chat structure
// (pb-chat, pb-msg, pb-cmsg, pb-sys) and the reply composer. Nothing here is raw: the orchestrator stores
// customer messages masked and masks the agent's before storing them, so `[NAME_1]` is what is on file.

import { parseBlocks, type MessageBlock } from "@pattern-blue/contracts";
import { useEffect, useRef, useState, type FormEvent } from "react";
import type { ErrorCategory } from "../api/errors";
import type { Outbox, TranscriptMessages } from "../machines/handoff";
import { useI18n } from "./context";
import { clockText } from "./format";
import { Alert, Icon, StateChip } from "./ui";

const dots = (masked: string) => masked.replaceAll("*", "•");

function Block({ block }: { block: MessageBlock }) {
  const { t } = useI18n();
  if (block.type === "receipt") {
    const { receipt } = block;
    return (
      <article className="pb-cmsg" data-tone="receipt" aria-label={t("handoff.transcript.receipt", { action: receipt.action })}>
        <div className="pb-cmsg__head">
          <span className="pb-cmsg__kicker">{t("handoff.transcript.receipt", { action: receipt.action })}</span>
        </div>
        <span className="pb-transition">
          <StateChip state={receipt.state_before} />
          <Icon name="arrow" />
          <StateChip state={receipt.state_after} />
        </span>
        <dl className="pb-kv">
          <dt>{t("handoff.transcript.target")}</dt>
          <dd>{dots(receipt.target_masked)}</dd>
          <dt>{t("handoff.transcript.audit")}</dt>
          <dd>{receipt.audit_id}</dd>
        </dl>
      </article>
    );
  }
  if (block.type === "handoff") {
    return (
      <div className="pb-sys" data-tone="joined">
        <span className="pb-sys__text">
          <Icon name="handoff" />
          {t("handoff.transcript.handoffBlock", { ref: block.handoff_id })}
        </span>
      </div>
    );
  }
  return null;
}

function Blocks({ raw }: { raw: unknown }) {
  const { t } = useI18n();
  const { blocks, unknown } = parseBlocks(raw);
  return (
    <>
      {blocks.filter((block) => block.type !== "text").map((block, index) => (
        <Block key={index} block={block} />
      ))}
      {unknown.map((item) => (
        <div key={`unknown-${item.index}`} className="pb-sys">
          <span className="pb-sys__text">{t("handoff.transcript.block", { type: item.type ?? t("common.unknown") })}</span>
        </div>
      ))}
    </>
  );
}

/** `agent@demo.local` -> `agent`: the design system labels a human agent by first name. */
export const agentName = (agentRef: string | null): string | null => (agentRef ? (agentRef.split("@")[0] ?? agentRef) : null);

export function TranscriptLog({ messages, agent }: { messages: TranscriptMessages; agent: string | null }) {
  const { t } = useI18n();
  const log = useRef<HTMLDivElement>(null);

  // Keep the newest message in view as the transcript grows.
  useEffect(() => {
    const element = log.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [messages.length]);

  let joined = false;
  return (
    <div className="pb-chat__log bo-log" role="log" aria-live="polite" aria-label={t("handoff.transcript.title")} ref={log}>
      {messages.length === 0 && <p className="pb-t-small">{t("handoff.transcript.empty")}</p>}
      {messages.map((message, index) => {
        const stamp = clockText(message.created_at);
        if (message.role === "user") {
          return (
            <div key={index} className="pb-msg pb-msg--customer">
              <span className="pb-msg__meta">{t("handoff.transcript.customer")} · {stamp}</span>
              {message.content}
            </div>
          );
        }
        if (message.role === "assistant") {
          return (
            <div key={index} className="bo-turn">
              {message.content !== "" && (
                <div className="pb-msg pb-msg--assistant">
                  <span className="pb-msg__meta">{t("handoff.transcript.assistant")} · {stamp}</span>
                  {message.content}
                </div>
              )}
              <Blocks raw={message.blocks} />
            </div>
          );
        }
        const name = agent ?? t("common.unknown");
        const firstAgentMessage = !joined;
        joined = true;
        return (
          <div key={index} className="bo-turn">
            {firstAgentMessage && (
              <div className="pb-sys" data-tone="joined">
                <span className="pb-sys__text">
                  <Icon name="user" />
                  {t("handoff.transcript.joined", { agent: name })}
                </span>
              </div>
            )}
            <div className="pb-msg pb-msg--agent">
              <span className="pb-msg__meta">
                <Icon name="user" />
                {t("handoff.transcript.agent", { agent: name })} · {stamp}
              </span>
              {message.content}
            </div>
          </div>
        );
      })}
    </div>
  );
}

const SEND_ERROR_KEY = {
  turnInProgress: "handoff.composer.turnInProgress",
  noActiveTakeover: "handoff.composer.noActiveTakeover",
  unavailable: "errors.unavailable",
} as const;

export function Composer({
  enabled,
  lockedReason,
  sending,
  failed,
  outbox,
  error,
  onSend,
  onRetry,
  onDiscard,
}: {
  enabled: boolean;
  lockedReason: "locked" | "lockedOther";
  sending: boolean;
  failed: boolean;
  outbox: Outbox | null;
  error: ErrorCategory | null;
  onSend: (text: string) => void;
  onRetry: () => void;
  onDiscard: () => void;
}) {
  const { t } = useI18n();
  const [text, setText] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!enabled || sending || text.trim() === "") return;
    onSend(text);
    setText("");
  };

  const errorText = error === null ? null : t(error === "turnInProgress" || error === "noActiveTakeover" || error === "unavailable" ? SEND_ERROR_KEY[error] : "errors.generic");

  return (
    <div className="bo-composer-wrap">
      {failed && outbox && (
        <div className="bo-failed">
          <div className="pb-msg pb-msg--agent" data-status="failed">
            <span className="pb-msg__meta">
              <Icon name="warning" />
              {t("handoff.composer.notSent")}
            </span>
            {outbox.text}
          </div>
          <Alert
            tone="caution"
            eyebrow={t("handoff.composer.notSent")}
            action={
              <span className="bo-actions">
                <button type="button" className="pb-btn pb-btn--secondary pb-btn--sm" onClick={onRetry}>
                  {t("handoff.composer.resend")}
                </button>
                <button type="button" className="pb-btn pb-btn--ghost pb-btn--sm" onClick={onDiscard}>
                  {t("handoff.composer.discard")}
                </button>
              </span>
            }
          >
            {errorText}
          </Alert>
        </div>
      )}
      <form className="pb-chat__composer" onSubmit={submit}>
        <label className="pb-field">
          <span className="pb-sr">{t("handoff.composer.label")}</span>
          <input
            type="text"
            value={text}
            maxLength={2000}
            autoComplete="off"
            disabled={!enabled || sending}
            placeholder={enabled ? t("handoff.composer.placeholder") : t(`handoff.composer.${lockedReason}`)}
            onChange={(event) => setText(event.target.value)}
          />
        </label>
        <button type="submit" className="pb-btn pb-btn--primary pb-btn--sm" disabled={!enabled || sending || text.trim() === ""}>
          {sending ? t("handoff.composer.sending") : t("handoff.composer.send")}
        </button>
      </form>
      <p className="pb-t-small bo-composer-note">{t("handoff.composer.note")}</p>
    </div>
  );
}
