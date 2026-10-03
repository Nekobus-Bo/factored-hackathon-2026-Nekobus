// The dock: the launcher and the panel, pinned bottom-right (full screen on a phone). The panel is not modal
// (the page stays usable); opening it focuses the composer, and Escape or the close button closes it and
// returns focus to the launcher. The simulated inbox opens as a sheet over the messages; Escape closes the
// sheet first. This file connects the chat machine to the views; the views themselves take props.

import { useSelector } from "@xstate/react";
import { useEffect, useRef, useState } from "react";
import {
  conversationState,
  selectChip,
  selectSendDisabled,
  selectTyping,
  type ConversationState,
  type PendingSend,
} from "../../machines/chat.machine";
import { isOtpSendReceipt, lastEntryWith } from "../../machines/chat-model";
import { useActors, useI18n } from "../actors";
import { useNow } from "../hooks";
import { Icon } from "../ui/Icon";
import { StateChip, type ChipStateName } from "../ui/StateChip";
import { MessageText, Sender } from "./Blocks";
import { Composer } from "./Composer";
import { GoneStrip, OtpFoot, OtpNoticeStrip, OtpSheet, RateLimitedStrip, type OtpFootProps, type OtpSheetProps } from "./Notices";
import { Transcript, type PendingFailure } from "./Transcript";
import type { Dictionary } from "../../i18n";

const CHIP_LABEL: Record<ChipStateName, (dict: Dictionary) => string> = {
  anonymous: (dict) => dict.chat.chip.anonymous,
  identified: (dict) => dict.chat.chip.identified,
  "otp-pending": (dict) => dict.chat.chip.otpPending,
  verified: (dict) => dict.chat.chip.verified,
  locked: (dict) => dict.chat.chip.locked,
  "handed-off": (dict) => dict.chat.chip.handedOff,
  active: (dict) => dict.chat.chip.active,
  blocked: (dict) => dict.chat.chip.blocked,
};

/** The message that just failed and what its line says: the reason only for a 503, the retry once allowed. */
function failureOf(state: ConversationState, pending: PendingSend | null, dict: Dictionary): PendingFailure | null {
  if (!pending) return null;
  if (state === "unavailable") return { entryId: pending.entryId, retry: true, reason: dict.chat.unavailable.text };
  if (state === "retryable") return { entryId: pending.entryId, retry: true, reason: null };
  if (state === "rateLimited" || state === "gone") return { entryId: pending.entryId, retry: false, reason: null };
  return null;
}

export function ChatDock({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { chat } = useActors();
  const { lang, dict } = useI18n();
  const snapshot = useSelector(chat, (value) => value);
  const state = conversationState(snapshot);
  const { entries, inbox, pending, retryUntil } = snapshot.context;
  const chip = selectChip(snapshot);

  const launcherRef = useRef<HTMLButtonElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const openerRef = useRef<HTMLButtonElement>(null);
  const revealRef = useRef<HTMLButtonElement>(null);
  const [inboxOpen, setInboxOpen] = useState(false);

  // The machine polls only while the tab is visible.
  useEffect(() => {
    const onChange = () => chat.send({ type: document.visibilityState === "visible" ? "VISIBLE" : "HIDDEN" });
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, [chat]);

  // Opening the panel moves focus to the composer.
  const wasOpen = useRef(false);
  useEffect(() => {
    if (open && !wasOpen.current) inputRef.current?.focus();
    wasOpen.current = open;
  }, [open]);

  // The sheet closes with the code it shows.
  useEffect(() => {
    if (!inbox) setInboxOpen(false);
  }, [inbox]);

  // Opening the sheet moves focus to "Mostrar código".
  useEffect(() => {
    if (inboxOpen) revealRef.current?.focus();
  }, [inboxOpen]);

  // New things arrive at the bottom of the log.
  const typing = selectTyping(snapshot);
  useEffect(() => {
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [entries.length, typing, state, inbox, open]);

  const close = () => {
    onOpenChange(false);
    launcherRef.current?.focus();
  };
  /** Closed by the customer (the button, Escape, the scrim): focus goes back to the action that opened it. */
  const closeSheet = () => {
    setInboxOpen(false);
    openerRef.current?.focus();
  };

  const hasOtpReceipt = lastEntryWith(entries, isOtpSendReceipt) !== null;
  const inboxProps = inbox
    ? { dict, notice: inbox, open: inboxOpen, onToggle: () => setInboxOpen((value) => !value), openerRef }
    : null;

  return (
    <div className="pb-dock">
      <section
        className="pb-chat pb-dock__panel"
        id="dock-panel"
        aria-label={dict.chat.panel}
        hidden={!open}
        onKeyDown={(event) => {
          if (event.key !== "Escape") return;
          if (inboxOpen) {
            event.stopPropagation();
            closeSheet();
          } else {
            close();
          }
        }}
      >
        <header className="pb-chat__head">
          <span className="pb-chat__title">
            <Icon name="hex" /> {dict.chat.title}
          </span>
          {chip && (
            <span className="chat-head-chip">
              <StateChip state={chip} label={CHIP_LABEL[chip](dict)} />
            </span>
          )}
          <button className="pb-btn pb-btn--ghost pb-btn--icon pb-btn--sm" type="button" aria-label={dict.chat.close} data-close-chat onClick={close}>
            <Icon name="x" />
          </button>
        </header>
        <div className="pb-chat__body">
          <div ref={logRef} className="pb-chat__log" role="log" aria-live="polite" aria-label={dict.chat.log}>
            <div className="pb-msg pb-msg--assistant">
              <Sender name={dict.chat.roles.assistant} />
              <MessageText text={dict.chat.greeting} />
            </div>
            <Transcript
              entries={entries}
              lang={lang}
              failure={failureOf(state, pending, dict)}
              onRetry={() => chat.send({ type: "RETRY" })}
              otpFoot={inboxProps && hasOtpReceipt ? <LiveOtpFoot {...inboxProps} /> : undefined}
            />
            {inboxProps && !hasOtpReceipt && <LiveOtpNoticeStrip {...inboxProps} />}
            {typing && (
              <div className="pb-typing" role="status">
                <span className="pb-sr">{dict.chat.typing}</span>
                <i />
                <i />
                <i />
              </div>
            )}
            {state === "rateLimited" && <LiveRateLimited dict={dict} retryUntil={retryUntil} />}
            {state === "gone" && <GoneStrip dict={dict} onStartOver={() => chat.send({ type: "RETRY" })} />}
          </div>
          {inbox && inboxOpen && (
            <>
              <div className="pb-chat__scrim" aria-hidden="true" onClick={closeSheet} />
              <LiveOtpSheet
                dict={dict}
                notice={inbox}
                onClose={closeSheet}
                onReveal={() => chat.send({ type: "CODE.REVEAL" })}
                onHide={() => chat.send({ type: "CODE.HIDE" })}
                revealRef={revealRef}
              />
            </>
          )}
        </div>
        <Composer
          dict={dict}
          inputRef={inputRef}
          sendDisabled={selectSendDisabled(snapshot)}
          onSend={(text) => {
            setInboxOpen(false);
            chat.send({ type: "SEND", text, lang });
          }}
        />
      </section>
      <button
        ref={launcherRef}
        className="pb-launcher pb-launcher--label pb-dock__launcher"
        id="dock-launcher"
        type="button"
        aria-label={dict.chat.launcher}
        aria-expanded={open}
        aria-controls="dock-panel"
        onClick={() => onOpenChange(!open)}
      >
        <Icon name="chat" />
        <span aria-hidden="true">{dict.chat.launcherLabel}</span>
      </button>
    </div>
  );
}

// The countdowns tick once a second, and only while they are on screen.

function LiveOtpFoot(props: Omit<OtpFootProps, "now">) {
  return <OtpFoot {...props} now={useNow(1000)} />;
}

function LiveOtpNoticeStrip(props: Omit<OtpFootProps, "now">) {
  return <OtpNoticeStrip {...props} now={useNow(1000)} />;
}

function LiveOtpSheet(props: Omit<OtpSheetProps, "now">) {
  return <OtpSheet {...props} now={useNow(1000)} />;
}

/** The wait a 429 asked for, counting down. */
function LiveRateLimited({ dict, retryUntil }: { dict: Dictionary; retryUntil: number | null }) {
  const now = useNow(1000);
  const seconds = Math.max(0, Math.ceil(((retryUntil ?? now) - now) / 1000));
  return <RateLimitedStrip dict={dict} seconds={seconds} />;
}
