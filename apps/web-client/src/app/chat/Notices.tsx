// Degraded states and the simulated inbox. Calm by rule: no hazard stripe in the chat, one sentence that says
// what happened and what to do, `role="status"` (a 503 is told under the message itself, as an alert).

import type { CSSProperties, Ref } from "react";
import { format, formatWait, type Dictionary } from "../../i18n";
import { formatCountdown } from "../../machines/chat-model";
import type { InboxNotice } from "../../machines/chat.machine";
import { Icon } from "../ui/Icon";

/** 429: the wait in minutes, from the Retry-After the server sent. `seconds` is what is left of it. */
export function RateLimitedStrip({ dict, seconds }: { dict: Dictionary; seconds: number }) {
  return (
    <p className="pb-cut pb-strip" role="status">
      <Icon name="clock" />
      <span>{format(dict.chat.rateLimited.text, { wait: formatWait(dict, seconds) })}</span>
    </p>
  );
}

/** 404: the conversation is not there any more. */
export function GoneStrip({ dict, onStartOver }: { dict: Dictionary; onStartOver: () => void }) {
  return (
    <p className="pb-cut pb-strip" data-tone="info" role="status">
      <Icon name="info" />
      <span>{dict.chat.gone.text}</span>
      <button className="pb-action" type="button" onClick={onStartOver}>
        {dict.chat.gone.action}
        <Icon name="retry" />
      </button>
    </p>
  );
}

// --- The simulated inbox ---------------------------------------------------------------------------------------------

export const INBOX_SHEET_ID = "otp-inbox";
const GAUGE_SEGMENTS = 24;

function countdownOf(notice: InboxNotice, now: number) {
  const expiresMs = Date.parse(notice.message.expires_at);
  const totalMs = Math.max(1, expiresMs - Date.parse(notice.message.received_at));
  const remainingMs = Math.max(0, expiresMs - now);
  return { remainingMs, totalMs, text: formatCountdown(remainingMs) };
}

export interface OtpFootProps {
  dict: Dictionary;
  notice: InboxNotice;
  /** Epoch milliseconds: the countdown counts to `expires_at` from here. */
  now: number;
  /** The sheet with the code is open. */
  open: boolean;
  onToggle: () => void;
  openerRef?: Ref<HTMLButtonElement>;
}

/** Inside the `otp.send` receipt while the code is live: the time left and the action that opens the inbox. */
export function OtpFoot({ dict, notice, now, open, onToggle, openerRef }: OtpFootProps) {
  const t = dict.chat.inbox;
  return (
    <div className="pb-proof__foot">
      <span>
        {t.expiresIn} <b role="timer">{countdownOf(notice, now).text}</b>
      </span>
      <InboxAction dict={dict} open={open} onToggle={onToggle} openerRef={openerRef} />
    </div>
  );
}

/** The same, on its own, when the log holds no `otp.send` receipt to carry it. */
export function OtpNoticeStrip({ dict, notice, now, open, onToggle, openerRef }: OtpFootProps) {
  const t = dict.chat.inbox;
  return (
    <div className="pb-cut pb-strip" data-tone="info">
      <Icon name="mail" />
      <span>
        {format(t.noticeFallback, { destination: notice.message.destination_masked })} {t.expiresIn}{" "}
        <b role="timer">{countdownOf(notice, now).text}</b>
      </span>
      <InboxAction dict={dict} open={open} onToggle={onToggle} openerRef={openerRef} />
    </div>
  );
}

function InboxAction({ dict, open, onToggle, openerRef }: { dict: Dictionary; open: boolean; onToggle: () => void; openerRef?: Ref<HTMLButtonElement> }) {
  return (
    <button ref={openerRef} className="pb-action" type="button" aria-expanded={open} aria-controls={INBOX_SHEET_ID} onClick={onToggle}>
      {dict.chat.inbox.open}
      <Icon name="arrow" />
    </button>
  );
}

export interface OtpSheetProps {
  dict: Dictionary;
  notice: InboxNotice;
  now: number;
  onClose: () => void;
  onReveal: () => void;
  onHide: () => void;
  revealRef?: Ref<HTMLButtonElement>;
}

/**
 * The simulated inbox, as a sheet over the lower part of the messages. The code is drawn only after the
 * customer asks for it; until then the cells hold bullets and the label says it is hidden. Nothing here
 * writes to the transcript. "Simulada" and "Demo" stay visible: no real email is sent.
 */
export function OtpSheet({ dict, notice, now, onClose, onReveal, onHide, revealRef }: OtpSheetProps) {
  const t = dict.chat.inbox;
  const { message, revealed } = notice;
  const { remainingMs, totalMs, text } = countdownOf(notice, now);
  const lit = Math.max(0, Math.min(GAUGE_SEGMENTS, Math.round((remainingMs / totalMs) * GAUGE_SEGMENTS)));
  const digits = Array.from(message.code);
  return (
    <section className="pb-cut pb-sheet" id={INBOX_SHEET_ID} aria-labelledby={`${INBOX_SHEET_ID}-title`}>
      <header className="pb-sheet__bar">
        <h2 className="pb-chat__title" id={`${INBOX_SHEET_ID}-title`}>
          {t.panelTitle}
        </h2>
        <span className="pb-tag">{t.demoTag}</span>
        <button className="pb-btn pb-btn--ghost pb-btn--icon pb-btn--sm" type="button" aria-label={t.close} onClick={onClose}>
          <Icon name="x" />
        </button>
      </header>
      <p className="pb-sheet__from">
        <b>{t.fromValue}</b> · {t.subjectValue}
      </p>
      <div className="pb-code" role="img" aria-label={revealed ? format(t.codeAria, { digits: digits.join(" ") }) : t.codeHiddenAria}>
        {digits.map((digit, index) => (
          <span className="pb-code__d" aria-hidden="true" key={index}>
            {revealed ? digit : "•"}
          </span>
        ))}
      </div>
      <div className="pb-sheet__row">
        <button ref={revealRef} className="pb-btn pb-btn--secondary pb-btn--sm" type="button" onClick={revealed ? onHide : onReveal}>
          {revealed ? t.hide : t.reveal}
        </button>
        <span className="pb-sheet__exp">
          {t.expiresIn} <b role="timer">{text}</b>
        </span>
      </div>
      <div
        className="pb-gauge pb-gauge--sm"
        style={{ "--n": GAUGE_SEGMENTS, "--on": lit } as CSSProperties}
        data-state={remainingMs < 60_000 ? "abstained" : "decided"}
        aria-hidden="true"
      >
        <div className="pb-gauge__track">
          <div className="pb-gauge__fill" />
        </div>
      </div>
      <p className="pb-sheet__note">
        <Icon name="info" />
        <span>{t.note}</span>
      </p>
    </section>
  );
}
