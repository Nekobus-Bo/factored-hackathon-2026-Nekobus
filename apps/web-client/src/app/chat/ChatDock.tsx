// The dock: the launcher and the panel, pinned bottom-right. The panel is not modal (the page stays
// usable); opening it focuses the composer, and Escape or the close button closes it and returns focus to
// the launcher. This file connects the chat machine to the views; the views themselves take props.

import { useSelector } from "@xstate/react";
import { useEffect, useRef, useState } from "react";
import {
  conversationState,
  selectChip,
  selectSendDisabled,
  selectTyping,
} from "../../machines/chat.machine";
import { useActors, useI18n } from "../actors";
import { useNow } from "../hooks";
import { Icon } from "../ui/Icon";
import { StateChip, type ChipStateName } from "../ui/StateChip";
import { Composer } from "./Composer";
import { GoneCard, OtpNotice, RateLimitedCard, UnavailableCard, type OtpNoticeProps } from "./Notices";
import { Transcript } from "./Transcript";
import type { Dictionary } from "../../i18n";
import { MessageText } from "./Blocks";

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

export function ChatDock({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { chat } = useActors();
  const { lang, dict } = useI18n();
  const snapshot = useSelector(chat, (value) => value);
  const state = conversationState(snapshot);
  const { entries, inbox, pending, retryUntil } = snapshot.context;
  const chip = selectChip(snapshot);

  const panelRef = useRef<HTMLElement>(null);
  const launcherRef = useRef<HTMLButtonElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
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

  // The notice closes with the message it belongs to.
  useEffect(() => {
    if (!inbox) setInboxOpen(false);
  }, [inbox]);

  // New things arrive at the bottom of the log.
  const typing = selectTyping(snapshot);
  useEffect(() => {
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [entries.length, typing, state, inbox, inboxOpen, open]);

  const close = () => {
    onOpenChange(false);
    launcherRef.current?.focus();
  };

  return (
    <div className="pb-dock">
      <section
        ref={panelRef}
        className="pb-chat pb-dock__panel"
        id="dock-panel"
        aria-label={dict.chat.panel}
        hidden={!open}
        onKeyDown={(event) => {
          if (event.key === "Escape") close();
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
        <div ref={logRef} className="pb-chat__log" role="log" aria-live="polite" aria-label={dict.chat.log}>
          <div className="pb-msg pb-msg--assistant">
            <span className="pb-msg__meta">{dict.chat.roles.assistant}</span>
            <MessageText text={dict.chat.greeting} />
          </div>
          <Transcript
            entries={entries}
            lang={lang}
            retryEntryId={state === "retryable" ? (pending?.entryId ?? null) : null}
            onRetry={() => chat.send({ type: "RETRY" })}
          />
          {inbox && (
            <LiveOtpNotice
              dict={dict}
              notice={inbox}
              open={inboxOpen}
              onToggle={() => setInboxOpen((value) => !value)}
              onReveal={() => chat.send({ type: "CODE.REVEAL" })}
              onHide={() => chat.send({ type: "CODE.HIDE" })}
            />
          )}
          {typing && (
            <div className="pb-typing" role="status">
              <span className="pb-sr">{dict.chat.typing}</span>
              <i />
              <i />
              <i />
            </div>
          )}
          {state === "unavailable" && <UnavailableCard dict={dict} onRetry={() => chat.send({ type: "RETRY" })} />}
          {state === "rateLimited" && <LiveRateLimited dict={dict} retryUntil={retryUntil} />}
          {state === "gone" && <GoneCard dict={dict} onStartOver={() => chat.send({ type: "RETRY" })} />}
        </div>
        <Composer
          dict={dict}
          inputRef={inputRef}
          sendDisabled={selectSendDisabled(snapshot)}
          onSend={(text) => chat.send({ type: "SEND", text, lang })}
        />
      </section>
      <button
        ref={launcherRef}
        className="pb-launcher pb-dock__launcher"
        id="dock-launcher"
        type="button"
        aria-label={dict.chat.launcher}
        aria-expanded={open}
        aria-controls="dock-panel"
        onClick={() => onOpenChange(!open)}
      >
        <Icon name="chat" />
      </button>
    </div>
  );
}

/** The notice with a countdown that ticks once a second, and only while the notice is on screen. */
function LiveOtpNotice(props: Omit<OtpNoticeProps, "now">) {
  const now = useNow(1000);
  return <OtpNotice {...props} now={now} />;
}

/** The wait a 429 asked for, counting down. */
function LiveRateLimited({ dict, retryUntil }: { dict: Dictionary; retryUntil: number | null }) {
  const now = useNow(1000);
  const seconds = Math.max(0, Math.ceil(((retryUntil ?? now) - now) / 1000));
  return <RateLimitedCard dict={dict} seconds={seconds} />;
}
