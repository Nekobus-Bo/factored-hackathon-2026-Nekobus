// The agent's view of a conversation (the declutter review of 2026-10-02): the customer on the left, the
// bank on the right (the assistant in grey, the agent in violet), each name once per run of messages,
// the time at the end of the bubble, and the engine's receipts and handoff as one sentence-case line each.
//
// The customer's messages are masked at the source and shown as stored. The agent's own messages are
// shown as written: the orchestrator keeps that text encrypted next to its masked twin and answers with it
// (ADR-0013, amendment 2026-09-29). The transcript does not say which agent wrote a message, so agent
// messages are labelled by who holds the conversation now.

import { parseBlocks, type MessageBlock } from "@pattern-blue/contracts";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import type { ErrorCategory } from "../api/errors";
import type { Outbox, TranscriptMessages } from "../machines/handoff";
import { shortMask } from "./CaseFacts";
import { useI18n } from "./context";
import { agentName } from "./Decisions";
import { clockText } from "./format";
import { Alert, Icon } from "./ui";

export { agentName };

type Message = TranscriptMessages[number];

function SysLine({ tone, icon, children, reference }: { tone?: string; icon: string; children: string; reference?: string }) {
  return (
    <div className="pb-sys" data-tone={tone}>
      <span className="pb-sys__text">
        <Icon name={icon} />
        {children}
        {reference && <span className="pb-sys__ref">· {reference}</span>}
      </span>
    </div>
  );
}

function BlockLine({ block }: { block: MessageBlock }) {
  const { t } = useI18n();
  if (block.type === "receipt") {
    const { receipt } = block;
    const target = shortMask(receipt.target_masked);
    if (receipt.action === "card.block") {
      return (
        <SysLine tone="locked" icon="card-blocked" reference={receipt.audit_id}>
          {t("handoff.transcript.cardBlocked", { target })}
        </SysLine>
      );
    }
    if (receipt.action === "otp.send") {
      return (
        <SysLine icon="mail" reference={receipt.audit_id}>
          {t("handoff.transcript.codeSent", { target: receipt.target_masked.replaceAll("*", "•") })}
        </SysLine>
      );
    }
    if (receipt.action === "otp.verify") {
      const verified = receipt.state_after === "VERIFIED";
      return (
        <SysLine tone={verified ? "verified" : "locked"} icon={verified ? "shield-check" : "lock"} reference={receipt.audit_id}>
          {verified ? t("handoff.transcript.verified") : t("handoff.transcript.lockedOut")}
        </SysLine>
      );
    }
    return (
      <SysLine icon="check" reference={receipt.audit_id}>
        {t("handoff.transcript.receipt", { action: receipt.action })}
      </SysLine>
    );
  }
  if (block.type === "handoff") {
    return (
      <SysLine tone="joined" icon="handoff">
        {t("handoff.transcript.handoffTo", { department: t(`enums.department.${block.department}`) })}
      </SysLine>
    );
  }
  return null;
}

function Blocks({ raw }: { raw: unknown }) {
  const { t } = useI18n();
  const { blocks, unknown } = parseBlocks(raw);
  return (
    <>
      {blocks
        .filter((block) => block.type !== "text")
        .map((block, index) => (
          <BlockLine key={index} block={block} />
        ))}
      {unknown.map((item) => (
        <SysLine key={`unknown-${item.index}`} icon="info">
          {t("handoff.transcript.block", { type: item.type ?? t("common.unknown") })}
        </SysLine>
      ))}
    </>
  );
}

type Side = "customer" | "assistant" | "agent";
const sideOf = (message: Message): Side => (message.role === "user" ? "customer" : message.role === "assistant" ? "assistant" : "agent");

export function TranscriptLog({ messages, me, holder }: { messages: TranscriptMessages; me: string; holder: string | null }) {
  const { t } = useI18n();
  const log = useRef<HTMLDivElement>(null);

  // Keep the newest message in view as the transcript grows.
  useEffect(() => {
    const element = log.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [messages.length]);

  const agentLabel = holder === null ? t("handoff.transcript.agent") : holder === me ? t("handoff.transcript.you") : (agentName(holder) ?? t("handoff.transcript.agent"));
  const label: Record<Side, string> = { customer: t("handoff.transcript.customer"), assistant: t("handoff.transcript.assistant"), agent: agentLabel };

  const items: ReactNode[] = [];
  let previous: Side | null = null;
  let joined = false;
  messages.forEach((message, index) => {
    const side = sideOf(message);
    if (side === "agent" && !joined) {
      joined = true;
      items.push(
        <SysLine key={`joined-${index}`} tone="joined" icon="user">
          {holder === me ? t("handoff.transcript.joinedYou") : t("handoff.transcript.joined", { agent: agentLabel })}
        </SysLine>,
      );
      previous = null;
    }
    const showName = side !== previous;
    if (message.content !== "") {
      items.push(
        <div key={index} className={`pb-convo__grp${side === "customer" ? "" : " pb-convo__grp--bank"}`}>
          {showName && (
            <span className="pb-convo__who" data-me={side === "agent" && holder === me ? "" : undefined}>
              {label[side]}
            </span>
          )}
          <div className={`pb-msg pb-msg--${side}`}>
            {message.content}
            <span className="pb-msg__time">{clockText(message.created_at)}</span>
          </div>
        </div>,
      );
      previous = side;
    }
    if (message.role === "assistant") {
      const lines = <Blocks key={`blocks-${index}`} raw={message.blocks} />;
      items.push(lines);
      if (parseBlocks(message.blocks).blocks.some((block) => block.type !== "text")) previous = null;
    }
  });

  return (
    <div className="pb-convo__log" role="log" aria-live="polite" aria-label={t("handoff.transcript.title")} ref={log}>
      {messages.length === 0 && <p className="pb-t-small">{t("handoff.transcript.empty")}</p>}
      {items}
    </div>
  );
}

const SEND_ERROR_KEY = {
  turnInProgress: "handoff.composer.turnInProgress",
  noActiveTakeover: "handoff.composer.noActiveTakeover",
  unavailable: "errors.unavailable",
} as const;

export function Composer({
  sending,
  failed,
  outbox,
  error,
  onSend,
  onRetry,
  onDiscard,
}: {
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

  const submit = () => {
    if (sending || text.trim() === "") return;
    onSend(text);
    setText("");
  };
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    submit();
  };
  // Enter sends, Shift+Enter adds a line; Enter while an input method composes a word does neither.
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  const errorText =
    error === null ? null : t(error === "turnInProgress" || error === "noActiveTakeover" || error === "unavailable" ? SEND_ERROR_KEY[error] : "errors.generic");

  return (
    <div className="bo-composer-wrap">
      {failed && outbox && (
        <div className="bo-failed">
          <div className="pb-msg pb-msg--agent" data-status="failed">
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
      <form className="pb-chat__composer" onSubmit={onSubmit}>
        <label className="pb-field">
          <span className="pb-sr">{t("handoff.composer.label")}</span>
          <textarea rows={1} value={text} maxLength={2000} disabled={sending} placeholder={t("handoff.composer.placeholder")} onChange={(event) => setText(event.target.value)} onKeyDown={onKeyDown} />
        </label>
        <button type="submit" className="pb-btn pb-btn--primary pb-btn--sm" disabled={sending || text.trim() === ""}>
          {sending ? t("handoff.composer.sending") : t("handoff.composer.send")}
        </button>
      </form>
      <p className="pb-convo__note">{t("handoff.composer.note")}</p>
    </div>
  );
}

/** Before the case is the agent's: one line, and the way to take it when that is possible. */
export function ComposerLocked({ reason, onTake, taking }: { reason: "take" | "other"; onTake?: () => void; taking?: boolean }) {
  const { t } = useI18n();
  return (
    <div className="pb-convo__locked">
      <span>{reason === "take" ? t("handoff.composer.locked") : t("handoff.composer.lockedOther")}</span>
      {reason === "take" && onTake && (
        <button type="button" className="pb-btn pb-btn--secondary pb-btn--sm" disabled={taking} onClick={onTake}>
          <Icon name="handoff" />
          {taking ? t("handoff.taking") : t("handoff.take")}
        </button>
      )}
    </div>
  );
}
