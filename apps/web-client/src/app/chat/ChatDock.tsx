// The dock: the launcher and the panel, pinned bottom-right (full screen on a phone). The panel is not modal
// (the page stays usable); opening it focuses the composer, and Escape or the close button closes it and
// returns focus to the launcher. The simulated inbox opens as a sheet over the messages; Escape closes the
// sheet first. After a handoff the log asks whether the assistant helped.
//
// The demo panel: where there is room (920px and more) one panel sits at the left of the chat, as tall as it, with
// two tabs, the demo guide and, where the environment offers detective mode, the trace view (ADR-0019). The header
// has one button, "Menú demo", that opens and closes it on the tab last used; the control under a reply opens the panel on that turn. The chat and its composer stay
// in sight and usable. Below 920px there is no room: the guide is not offered, and the detective view takes the
// place of the log and the composer inside the chat's panel, which stay mounted, hidden, so the scroll and the
// draft survive. Whether the panel is open, its tab and its turn are local to this component (see
// `detective-view.ts`) and start closed on every visit. Choosing a script opens a new conversation in the
// script's market; the page follows. This file connects the chat machine to the views; the views take props.

import type { DemoScriptId } from "@pattern-blue/contracts";
import { useSelector } from "@xstate/react";
import { useEffect, useLayoutEffect, useMemo, useReducer, useRef, useState } from "react";
import {
  conversationState,
  selectAwaitingRetry,
  selectCanStartScript,
  selectChip,
  selectCodeMode,
  selectFeedback,
  selectScript,
  selectSendDisabled,
  selectTyping,
  type ConversationState,
  type PendingSend,
} from "../../machines/chat.machine";
import { challengeKey, isOtpSendReceipt, lastEntryWith } from "../../machines/chat-model";
import { useActors, useI18n, useLocale } from "../actors";
import { useNow, useSidePanelRoom } from "../hooks";
import { Icon } from "../ui/Icon";
import { StateChip, type ChipStateName } from "../ui/StateChip";
import { MessageText, Sender } from "./Blocks";
import { requestNewCode } from "./code-actions";
import { CodeComposer } from "./CodeComposer";
import { Composer } from "./Composer";
import { effectiveTab, initialSidePanel, placement, selectedTurnId, shown, sidePanelReducer } from "./detective-view";
import { FeedbackLine } from "./Feedback";
import { sendGuideLine, startGuideScript } from "./guide-actions";
import { GuidePanel } from "./GuidePanel";
import { GoneStrip, OtpFoot, OtpNoticeStrip, OtpSheet, RateLimitedStrip, type OtpFootProps, type OtpSheetProps } from "./Notices";
import { SIDE_PANEL_ID, SidePanel } from "./SidePanel";
import { TracePanel, type TraceView } from "./TracePanel";
import { replyCount, tracedTurns } from "./trace-model";
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

/** The log is at the bottom when less than this many pixels are left to scroll. */
const AT_BOTTOM_PX = 8;

export function ChatDock({
  open,
  onOpenChange,
  startInDetective = false,
  startWithGuide = false,
  wide,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Starts with the panel open on the detective tab. Only the tests that render the dock on the server use it: a visit always starts closed. */
  startInDetective?: boolean;
  /** Starts with the panel open on the script tab. Only for the same tests. */
  startWithGuide?: boolean;
  /** Whether there is room for the panel beside the chat. Only the tests set it: the page asks the window. */
  wide?: boolean;
}) {
  const actors = useActors();
  const { chat } = actors;
  const { lang, dict } = useI18n();
  const { locale } = useLocale();
  const windowRoom = useSidePanelRoom();
  const room = wide ?? windowRoom;
  const snapshot = useSelector(chat, (value) => value);
  const state = conversationState(snapshot);
  const { entries, inbox, pending, retryUntil } = snapshot.context;
  const chip = selectChip(snapshot);
  // While a one-time code is pending the composer is the code field (see CodeComposer); the normal one stays mounted, hidden, so a draft survives.
  const codeMode = selectCodeMode(snapshot);
  const codeShown = codeMode.kind === "entry" || codeMode.kind === "expired";
  // Detective mode (ADR-0019): the switch exists only where the orchestrator says it is on.
  const detectiveOffered = snapshot.context.detective;

  const launcherRef = useRef<HTMLButtonElement>(null);
  const sectionRef = useRef<HTMLElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const codeInputRef = useRef<HTMLInputElement>(null);
  const codeRequestRef = useRef<HTMLButtonElement>(null);
  const guideTitleRef = useRef<HTMLParagraphElement>(null);
  const openerRef = useRef<HTMLButtonElement>(null);
  const revealRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLButtonElement>(null);
  const logScroll = useRef<{ top: number; atBottom: boolean } | null>(null);
  const [inboxOpen, setInboxOpen] = useState(false);
  const [view, dispatchView] = useReducer(sidePanelReducer, startInDetective ? "detective" : startWithGuide ? "script" : null, initialSidePanel);
  const [traceView, setTraceView] = useState<TraceView>("steps");
  // The detective tab exists only where the environment offers the mode: when the back office turns it off, the panel
  // is on the guide, or (with no room for a panel) the chat is back.
  const tab = effectiveTab(view, detectiveOffered);
  const { beside, inPlace } = placement(view, detectiveOffered, room);
  const panelShown = shown(view, detectiveOffered, room);
  const turns = useMemo(() => tracedTurns(entries), [entries]);
  const replies = useMemo(() => replyCount(entries), [entries]);
  const traceSelectedId = selectedTurnId(view, turns);

  // The machine polls only while the tab is visible.
  useEffect(() => {
    const onChange = () => chat.send({ type: document.visibilityState === "visible" ? "VISIBLE" : "HIDDEN" });
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, [chat]);

  /** The composer that is in sight: the code field (or its "Pedir otro código"), else the text area. */
  const focusComposer = () => {
    if (codeMode.kind === "entry") codeInputRef.current?.focus();
    else if (codeMode.kind === "expired") codeRequestRef.current?.focus();
    else inputRef.current?.focus();
  };

  /**
   * The same, but only if the customer's focus is free: nowhere (what had it went away), or in the chat. A customer in
   * the side panel or on the page keeps it. Run after the screen has caught up with what was just sent.
   */
  const focusComposerIfFree = () =>
    setTimeout(() => {
      const active = document.activeElement;
      if (!active || active === document.body || sectionRef.current?.contains(active)) focusComposer();
    }, 0);

  // Opening the chat moves focus to the composer (or, when it reopens on the detective view in place of the chat,
  // where the composer is hidden, to the header button), and asks whether detective mode is on.
  const wasOpen = useRef(false);
  useEffect(() => {
    if (open && !wasOpen.current) {
      if (inPlace) menuRef.current?.focus();
      else focusComposer();
      chat.send({ type: "CAPABILITIES.CHECK" });
    }
    wasOpen.current = open;
  }, [open, chat]);

  // A new turn: the panel follows it again.
  useEffect(() => {
    dispatchView({ type: "newTurn" });
  }, [turns.length]);

  // The mode turned off while the view was open: the chat is back, and it is back for good (a later "on" does not reopen the view).
  useEffect(() => {
    dispatchView({ type: "offered", offered: detectiveOffered });
  }, [detectiveOffered]);

  // The mode turned off with the focus on the Detective tab or in the trace: the trace is gone, the panel is on the
  // guide, and the focus goes to the guide's title instead of falling to the page.
  const wasOffered = useRef(detectiveOffered);
  useEffect(() => {
    if (wasOffered.current && !detectiveOffered && beside) {
      const active = document.activeElement;
      if (!active || active === document.body) guideTitleRef.current?.focus();
    }
    wasOffered.current = detectiveOffered;
  }, [detectiveOffered]);

  // The window turned too narrow for the panel beside the chat: a panel open on the guide would be open with nothing in
  // sight, so it closes (the detective tab goes on, in place of the chat). After the effect above, so a mode turned off
  // at the same time is already on the guide.
  useEffect(() => {
    dispatchView({ type: "room", room });
  }, [room, detectiveOffered]);

  // The detective view in place of the chat (a narrow window) moves focus: to the header button on the way in (the
  // reply's control is gone), to the composer on the way back, where the log is put at the scroll it had (or at the
  // bottom, if it was there and has grown).
  const wasDetective = useRef(inPlace);
  useLayoutEffect(() => {
    if (inPlace === wasDetective.current) return;
    wasDetective.current = inPlace;
    if (inPlace) {
      menuRef.current?.focus();
      return;
    }
    const log = logRef.current;
    const saved = logScroll.current;
    if (log && saved) log.scrollTop = saved.atBottom ? log.scrollHeight : saved.top;
    focusComposer();
  }, [inPlace]);

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

  /** Remembers where the log was, for the way back from the view that takes its place. */
  const saveLogScroll = () => {
    const log = logRef.current;
    if (log) logScroll.current = { top: log.scrollTop, atBottom: log.scrollHeight - log.clientHeight - log.scrollTop < AT_BOTTOM_PX };
  };
  /** Opening the detective tab asks again, so the back office turning the mode off takes the customer out of it without waiting for a turn. */
  const askCapabilities = () => chat.send({ type: "CAPABILITIES.CHECK" });
  /** The control under a reply: the panel opens on that turn. */
  const openTurn = (id: string) => {
    saveLogScroll();
    dispatchView({ type: "open", turnId: id });
    setInboxOpen(false);
    askCapabilities();
  };
  /**
   * The header button: opens the panel on the tab last used (the guide the first time) and closes it when it is
   * open. With no room for the panel the button exists only for the detective view, which it opens in place of the chat.
   */
  const toggleMenu = () => {
    const next = room ? tab : "detective";
    if (!panelShown && next === "detective") {
      saveLogScroll();
      askCapabilities();
    }
    dispatchView({ type: "toggle", tab: room ? undefined : "detective" });
  };

  /** The guide's clicks send. The chat stays in sight beside the panel, so only the composer takes the focus back. */
  const leaveForChat = () => {
    setInboxOpen(false);
    focusComposerIfFree();
  };
  /** A script was chosen: a new conversation in the script's market, and the page follows it. */
  const pickScript = (id: DemoScriptId) => {
    startGuideScript(actors, id);
    leaveForChat();
  };
  /** The script's next line, as written. */
  const sendScriptLine = (text: string) => {
    const script = snapshot.context.script;
    if (!script) return;
    sendGuideLine(actors, script, text);
    leaveForChat();
  };

  const close = () => {
    onOpenChange(false);
    launcherRef.current?.focus();
  };
  /** Closed by the customer (the button, Escape, the scrim): focus goes back to the action that opened it. */
  const closeSheet = () => {
    setInboxOpen(false);
    openerRef.current?.focus();
  };

  // After "Cancelar" the code is still live: the notice offers the way back to the field.
  const writeCode = codeMode.kind === "dismissed" && codeMode.resumable ? () => chat.send({ type: "CODE.RESUME" }) : undefined;

  // The code field ends (cancelled, verified, locked): the normal composer takes the focus back.
  const wasCodeShown = useRef(false);
  useEffect(() => {
    if (wasCodeShown.current && !codeShown) inputRef.current?.focus();
    wasCodeShown.current = codeShown;
  }, [codeShown]);

  const hasOtpReceipt = lastEntryWith(entries, isOtpSendReceipt) !== null;
  const inboxProps = inbox
    ? { dict, notice: inbox, open: inboxOpen, onToggle: () => setInboxOpen((value) => !value), openerRef, onWrite: writeCode }
    : null;

  return (
    <div className="pb-dock">
      <section
        ref={sectionRef}
        className="pb-chat pb-dock__panel"
        id="dock-panel"
        aria-label={inPlace ? dict.chat.detective.toggle : dict.chat.panel}
        hidden={!open}
        onKeyDown={(event) => {
          if (event.key !== "Escape") return;
          if (inPlace) {
            event.stopPropagation();
            dispatchView({ type: "close" });
          } else if (inboxOpen) {
            event.stopPropagation();
            closeSheet();
          } else {
            close();
          }
        }}
      >
        <header className="pb-chat__head">
          <span className="pb-chat__title">
            <Icon name={inPlace ? "detective" : "hex"} /> {inPlace ? dict.chat.detective.toggle : dict.chat.title}
          </span>
          {chip && !inPlace && (
            <span className="chat-head-chip">
              <StateChip state={chip} label={CHIP_LABEL[chip](dict)} />
            </span>
          )}
          {(room || detectiveOffered) && (
            <button
              ref={menuRef}
              className={`pb-btn ${panelShown ? "pb-btn--primary" : "pb-btn--secondary"} pb-btn--sm pb-demo-toggle${inPlace ? " pb-btn--icon" : ""}`}
              type="button"
              aria-label={inPlace ? dict.chat.detective.back : dict.chat.demo.menu}
              title={inPlace ? dict.chat.detective.back : dict.chat.demo.menu}
              // In place of the chat the button is "Volver al chat": no pressed state, and nothing it controls (the panel is hidden then).
              aria-pressed={inPlace ? undefined : panelShown}
              aria-controls={room ? SIDE_PANEL_ID : undefined}
              data-demo-toggle
              data-seen={view.seen ? "true" : undefined}
              onClick={toggleMenu}
            >
              <Icon name={inPlace ? "chat" : "menu"} />
              {!inPlace && <span className="pb-demo-toggle__text">{dict.chat.demo.menu}</span>}
            </button>
          )}
          <button className="pb-btn pb-btn--ghost pb-btn--icon pb-btn--sm" type="button" aria-label={dict.chat.close} data-close-chat onClick={close}>
            <Icon name="x" />
          </button>
        </header>
        {inPlace && (
          <TracePanel dict={dict} turns={turns} total={replies} selectedId={traceSelectedId} view={traceView} onSelect={(turnId) => dispatchView({ type: "select", turnId })} onView={setTraceView} />
        )}
        <div className="pb-chat__body" hidden={inPlace}>
          <div ref={logRef} className="pb-chat__log" role="log" aria-live="polite" aria-label={dict.chat.log}>
            <div className="pb-msg pb-msg--assistant">
              <Sender name={dict.chat.roles.assistant} />
              <MessageText text={dict.chat.greeting} />
            </div>
            <Transcript
              entries={entries}
              lang={lang}
              detective={detectiveOffered}
              onOpenTrace={openTurn}
              failure={failureOf(state, pending, dict)}
              onRetry={() => chat.send({ type: "RETRY" })}
              otpFoot={inboxProps && hasOtpReceipt ? <LiveOtpFoot {...inboxProps} /> : undefined}
              afterHandoff={
                <FeedbackLine
                  dict={dict}
                  state={selectFeedback(snapshot)}
                  onAnswer={(helpful) => chat.send({ type: "FEEDBACK.SEND", helpful })}
                />
              }
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
        {(codeMode.kind === "entry" || codeMode.kind === "expired") && (
          <CodeComposer
            // A new code is a new challenge: a new field, empty (and the digits of the old one never complete it).
            key={challengeKey(entries) ?? "code"}
            dict={dict}
            inputRef={codeInputRef}
            requestRef={codeRequestRef}
            mode={codeMode}
            sendDisabled={selectSendDisabled(snapshot)}
            hidden={inPlace}
            onSend={(code) => {
              setInboxOpen(false);
              chat.send({ type: "SEND", text: code, lang, locale });
            }}
            onCancel={() => chat.send({ type: "CODE.DISMISS" })}
            onRequestNew={() => {
              setInboxOpen(false);
              requestNewCode(actors, entries, lang, locale);
            }}
          />
        )}
        <Composer
          dict={dict}
          inputRef={inputRef}
          hidden={inPlace || codeShown}
          sendDisabled={selectSendDisabled(snapshot)}
          onSend={(text) => {
            setInboxOpen(false);
            chat.send({ type: "SEND", text, lang, locale });
          }}
        />
      </section>
      <SidePanel
        dict={dict}
        hidden={!open || !beside}
        tab={tab}
        detectiveOffered={detectiveOffered}
        onTab={(name) => {
          if (name === "detective" && tab !== "detective") askCapabilities();
          dispatchView({ type: "tab", tab: name });
        }}
        onClose={() => {
          dispatchView({ type: "close" });
          menuRef.current?.focus();
        }}
      >
        {!open || !beside ? null : tab === "detective" ? (
          <TracePanel dict={dict} turns={turns} total={replies} selectedId={traceSelectedId} view={traceView} onSelect={(turnId) => dispatchView({ type: "select", turnId })} onView={setTraceView} />
        ) : (
          <GuidePanel
            dict={dict}
            script={selectScript(snapshot)}
            disabled={selectSendDisabled(snapshot)}
            chooseDisabled={!selectCanStartScript(snapshot)}
            awaitingRetry={selectAwaitingRetry(snapshot)}
            titleRef={guideTitleRef}
            onPick={pickScript}
            onSend={sendScriptLine}
            onReset={() => chat.send({ type: "SCRIPT.RESET" })}
          />
        )}
      </SidePanel>
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
