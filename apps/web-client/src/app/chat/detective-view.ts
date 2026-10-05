// The demo panel as a pure function (ADR-0019): open or not, which of its two tabs ("script", the demo guide;
// "detective", the trace view) and which turn the detective tab is on. Where it is is not state: it is derived from
// whether there is room, beside the chat or, with no room, in the chat panel's place, with both tabs in either. So a
// resize between the two keeps what was open. The state is local to the dock, starts closed on every visit and is never
// remembered. Apart from the component so the transitions can be tested without a DOM.

import type { TracedTurn } from "./trace-model";

export type SideTab = "script" | "detective";

export interface SidePanelState {
  /** The panel is open (beside the chat where there is room; in place of the chat where there is not). */
  open: boolean;
  tab: SideTab;
  /** The turn the detective tab was put on, or null: it follows the newest turn. */
  picked: string | null;
  /** The panel has been open at some point in this visit: the header button stops calling for attention for good. */
  seen: boolean;
}

export type SidePanelAction =
  /** The header button ("Menú demo"): opens the panel on the tab last used (the script the first time), and closes it when it is open. */
  | { type: "toggle" }
  /** The control under a reply: the panel opens on the detective tab with that turn. */
  | { type: "open"; turnId: string }
  /** One of the panel's tabs. Nothing else changes: the script in progress and the turn picked stay. */
  | { type: "tab"; tab: SideTab }
  /** The way back in place of the chat, or Escape inside the panel. */
  | { type: "close" }
  /** The stepper picked a turn. */
  | { type: "select"; turnId: string }
  /** A new turn arrived: the detective tab follows it again. */
  | { type: "newTurn" }
  /** The guide was used in place of the chat (a script picked, a line sent or copied): the panel closes, to show the chat. Beside the chat the dock does not dispatch it: nothing closes there. */
  | { type: "guideUsed" }
  /** What the environment says about the mode. Off sends the detective tab to the script and keeps it there, wherever the panel is: a later "on" does not bring it back. */
  | { type: "offered"; offered: boolean };

export const initialSidePanel = (tab: SideTab | null = null): SidePanelState => ({ open: tab !== null, tab: tab ?? "script", picked: null, seen: tab !== null });

/** The transitions, then the one rule that holds after any of them: a panel that has been open has been seen. */
export function sidePanelReducer(state: SidePanelState, action: SidePanelAction): SidePanelState {
  const next = transition(state, action);
  return next.open && !next.seen ? { ...next, seen: true } : next;
}

function transition(state: SidePanelState, action: SidePanelAction): SidePanelState {
  switch (action.type) {
    case "toggle":
      // Opened from closed, the detective tab follows the newest turn.
      return state.open ? { ...state, open: false } : { ...state, open: true, picked: null };
    case "open":
      return { ...state, open: true, tab: "detective", picked: action.turnId };
    case "tab":
      return state.tab === action.tab ? state : { ...state, tab: action.tab };
    case "close":
      return state.open ? { ...state, open: false } : state;
    case "select":
      return state.picked === action.turnId ? state : { ...state, picked: action.turnId };
    case "newTurn":
      return state.picked === null ? state : { ...state, picked: null };
    case "guideUsed":
      return state.open ? { ...state, open: false } : state;
    case "offered":
      return action.offered || state.tab !== "detective" ? state : { ...state, tab: "script" };
  }
}

/** The tab that shows: the detective one only where the environment offers the mode. */
export const effectiveTab = (state: SidePanelState, offered: boolean): SideTab => (state.tab === "detective" && !offered ? "script" : state.tab);

/** Where the panel is: beside the chat where there is room, in place of it where there is not. Both tabs, in either place. */
export function placement(state: SidePanelState, room: boolean): { beside: boolean; inPlace: boolean } {
  return { beside: state.open && room, inPlace: state.open && !room };
}

/** Whether the panel is showing, in either place. The header button's `aria-pressed` is this beside the chat; in place of it the button is the way back and has none. */
export const shown = (state: SidePanelState): boolean => state.open;

/**
 * The hero's "Hablar con el asistente" asks the dock for the composer by raising a counter. The dock focuses it only if the
 * counter moved and the chat was already open and still is: a click that opens a closed chat is the opening's own focus, and
 * must not be given twice.
 */
export const focusesOnRequest = (prev: number, next: number, wasOpen: boolean, open: boolean): boolean => next !== prev && wasOpen && open;

export type GuideUse = "pick" | "send" | "copy";
export type FocusTarget = "log" | "composer" | "composer-if-free";

/**
 * Where the focus goes once the guide was used: the one place that decides it.
 * - Copy: the composer, with the caret at the end, whatever the place (the composer fills and focuses itself, in the click).
 * - Pick or send beside the chat: the composer if the focus is free (the customer in the panel keeps it).
 * - Pick or send in place of the chat: the log, so the phone's keyboard does not open over the reply.
 */
export function focusAfterGuide(use: GuideUse, room: boolean): FocusTarget {
  if (use === "copy") return "composer";
  return room ? "composer-if-free" : "log";
}

/** The turn the detective tab is on: the one picked, else the newest. */
export const selectedTurnId = (state: SidePanelState, turns: readonly TracedTurn[]): string | null =>
  state.picked ?? turns[turns.length - 1]?.id ?? null;
