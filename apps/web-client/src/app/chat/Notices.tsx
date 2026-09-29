// Degraded states and the OTP notice. Calm by rule: no hazard stripe in the chat, what happened and
// what to do, a 503 is `role="alert"` and the rest `role="status"`.

import { format, formatWait, type Dictionary } from "../../i18n";
import { formatCountdown } from "../../machines/chat-model";
import type { InboxNotice } from "../../machines/chat.machine";
import { Icon } from "../ui/Icon";
import type { CSSProperties } from "react";

/** 503, or no network: the message was not processed, and retrying resends it under the same id. */
export function UnavailableCard({ dict, onRetry }: { dict: Dictionary; onRetry: () => void }) {
  const t = dict.chat.unavailable;
  return (
    <div className="pb-cmsg" data-tone="caution" role="alert">
      <span className="pb-cmsg__eyebrow">
        <Icon name="warning" />
        {t.eyebrow}
      </span>
      <p className="pb-cmsg__text">{t.text}</p>
      <div className="pb-cmsg__actions">
        <button className="pb-action" type="button" onClick={onRetry}>
          {dict.chat.retry}
          <Icon name="retry" />
        </button>
      </div>
    </div>
  );
}

/** 429: the wait in minutes, from the Retry-After the server sent. `seconds` is what is left of it. */
export function RateLimitedCard({ dict, seconds }: { dict: Dictionary; seconds: number }) {
  const t = dict.chat.rateLimited;
  return (
    <div className="pb-cmsg" data-tone="caution" role="status">
      <span className="pb-cmsg__eyebrow">
        <Icon name="clock" />
        {t.eyebrow}
      </span>
      <p className="pb-cmsg__text">{format(t.text, { wait: formatWait(dict, seconds) })}</p>
    </div>
  );
}

/** 404: the conversation is not there any more. */
export function GoneCard({ dict, onStartOver }: { dict: Dictionary; onStartOver: () => void }) {
  const t = dict.chat.gone;
  return (
    <div className="pb-cmsg" data-tone="info" role="status">
      <span className="pb-cmsg__eyebrow">
        <Icon name="info" />
        {t.eyebrow}
      </span>
      <p className="pb-cmsg__text">{t.text}</p>
      <div className="pb-cmsg__actions">
        <button className="pb-action" type="button" onClick={onStartOver}>
          {t.action}
          <Icon name="retry" />
        </button>
      </div>
    </div>
  );
}

// --- The OTP notice ---------------------------------------------------------------------------------------------------

const GAUGE_SEGMENTS = 24;

export interface OtpNoticeProps {
  dict: Dictionary;
  notice: InboxNotice;
  /** Epoch milliseconds: the countdown counts to `expires_at` from here. */
  now: number;
  /** The panel with the code is open. */
  open: boolean;
  onToggle: () => void;
  onReveal: () => void;
  onHide: () => void;
}

/**
 * "You got an email with the code": a notice, and the simulated inbox it opens. The code is drawn only
 * after the customer asks for it; until then the cells hold bullets and the label says it is hidden.
 * Nothing here writes to the transcript.
 */
export function OtpNotice({ dict, notice, now, open, onToggle, onReveal, onHide }: OtpNoticeProps) {
  const t = dict.chat.inbox;
  const { message, revealed } = notice;
  const expiresMs = Date.parse(message.expires_at);
  const totalMs = Math.max(1, expiresMs - Date.parse(message.received_at));
  const remainingMs = Math.max(0, expiresMs - now);
  const countdown = formatCountdown(remainingMs);
  const lit = Math.max(0, Math.min(GAUGE_SEGMENTS, Math.round((remainingMs / totalMs) * GAUGE_SEGMENTS)));
  const digits = Array.from(message.code);

  return (
    <>
      <div className="pb-cmsg pb-cmsg--notice" aria-label={t.noticeTitle}>
        <span className="pb-cmsg__icon" aria-hidden="true">
          <Icon name="mail" />
        </span>
        <p className="pb-cmsg__text">
          <strong>{t.noticeTitle}</strong>
          <br />
          <span className="pb-t-mono">{message.destination_masked}</span> · {t.expiresIn}{" "}
          <span className="pb-t-mono" role="timer">
            {countdown}
          </span>
        </p>
        <div className="pb-cmsg__actions">
          <button className="pb-action" type="button" aria-expanded={open} aria-controls="otp-inbox" onClick={onToggle}>
            {open ? t.close : t.open}
            <Icon name="arrow" />
          </button>
        </div>
      </div>
      {open && (
        <section className="pb-card pb-inbox" id="otp-inbox" aria-labelledby="otp-inbox-title">
          <header className="pb-inbox__bar">
            <h2 className="pb-chat__title chat-inbox-title" id="otp-inbox-title">
              {t.panelTitle}
            </h2>
            <span className="pb-tag">{t.demoTag}</span>
          </header>
          <div className="pb-inbox__body">
            <dl className="pb-kv">
              <dt>{t.from}</dt>
              <dd className="pb-kv__text">{t.fromValue}</dd>
              <dt>{t.to}</dt>
              <dd>{message.destination_masked}</dd>
              <dt>{t.subject}</dt>
              <dd className="pb-kv__text">{t.subjectValue}</dd>
            </dl>
            <p className="pb-t-body chat-flush">{t.instruction}</p>
            <div className="pb-code" role="img" aria-label={revealed ? format(t.codeAria, { digits: digits.join(" ") }) : t.codeHiddenAria}>
              {digits.map((digit, index) => (
                <span className="pb-code__d" aria-hidden="true" key={index}>
                  {revealed ? digit : "•"}
                </span>
              ))}
            </div>
            <div className="chat-inbox-actions">
              <button className="pb-btn pb-btn--secondary pb-btn--sm" type="button" onClick={revealed ? onHide : onReveal}>
                {revealed ? t.hide : t.reveal}
              </button>
            </div>
            <div className="pb-expiry">
              <div className="pb-expiry__row">
                <span className="pb-t-label">{t.expiryLabel}</span>
                <span className="pb-expiry__time" role="timer">
                  {countdown}
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
            </div>
            <p className="pb-inbox__note">
              <Icon name="info" />
              <span>{t.note}</span>
            </p>
            <p className="pb-t-small chat-flush">{t.security}</p>
          </div>
        </section>
      )}
    </>
  );
}
