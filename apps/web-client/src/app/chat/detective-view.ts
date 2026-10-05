// The demo panel at the left of the chat, as a pure function (ADR-0019): open or not, which of its two tabs
// ("script", the demo guide; "detective", the trace view) and which turn the detective tab is on. Below the width
// where the panel fits beside the chat there is no panel: the detective tab shows in place of the chat instead, and
// the script tab shows nothing. The state is local to the dock, starts closed on every visit and is never
// remembered. Apart from the component so the transitions can be tested without a DOM.

import type { TracedTurn } from "./trace-model";

export type SideTab = "script" | "detective";

export interface SidePanelState {
  /** The panel is open (beside the chat where there is room; the detective tab in place of the chat where there is not). */
  open: boolean;
  tab: SideTab;
  /** The turn the detective tab was put on, or null: it follows the newest turn. */
  picked: string | null;
  /** The panel has been open at some point in this visit: the header button stops calling for attention for good. */
  seen: boolean;
}

export type SidePanelAction =
  /**
   * The header button ("Menú demo"): opens the panel on the tab last used (the script the first time), and closes it
   * when it is open. With no room for the panel the only tab that shows is the detective one, and the button names it
   * (`tab: "detective"`): that is the one use of the explicit tab.
   */
  | { type: "toggle"; tab?: "detective" }
  /** The control under a reply: the panel opens on the detective tab with that turn. */
  | { type: "open"; turnId: string }
  /** One of the panel's tabs. Nothing else changes: the script in progress and the turn picked stay. */
  | { type: "tab"; tab: SideTab }
  /** The way back in the narrow view, or Escape inside the panel. */
  | { type: "close" }
  /** The stepper picked a turn. */
  | { type: "select"; turnId: string }
  /** A new turn arrived: the detective tab follows it again. */
  | { type: "newTurn" }
  /** Whether there is room for the panel beside the chat. With none, a panel open on the script closes: it would be open with nothing in sight. */
  | { type: "room"; room: boolean }
  /** What the environment says about the mode. Off sends the detective tab to the script and keeps it there: a later "on" does not bring it back. */
  | { type: "offered"; offered: boolean };

export const initialSidePanel = (tab: SideTab | null = null): SidePanelState => ({ open: tab !== null, tab: tab ?? "script", picked: null, seen: tab !== null });

/** The transitions, then the one rule that holds after any of them: a panel that has been open has been seen. */
export function sidePanelReducer(state: SidePanelState, action: SidePanelAction): SidePanelState {
  const next = transition(state, action);
  return next.open && !next.seen ? { ...next, seen: true } : next;
}

function transition(state: SidePanelState, action: SidePanelAction): SidePanelState {
  switch (action.type) {
    case "toggle": {
      const tab = action.tab ?? state.tab;
      if (state.open && state.tab === tab) return { ...state, open: false };
      // Opened from closed, the detective tab follows the newest turn; switched while open, it keeps its turn.
      return { ...state, open: true, tab, picked: state.open ? state.picked : null };
    }
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
    case "room":
      return action.room || !state.open || state.tab !== "script" ? state : { ...state, open: false };
    case "offered":
      return action.offered || state.tab !== "detective" ? state : { ...state, tab: "script" };
  }
}

/** The tab that shows: the detective one only where the environment offers the mode. */
export const effectiveTab = (state: SidePanelState, offered: boolean): SideTab => (state.tab === "detective" && !offered ? "script" : state.tab);

/** Where the panel is: beside the chat (where there is room) or, on the detective tab only, in place of the chat. */
export function placement(state: SidePanelState, offered: boolean, room: boolean): { beside: boolean; inPlace: boolean } {
  const shown = state.open && (room || (offered && effectiveTab(state, offered) === "detective"));
  return { beside: shown && room, inPlace: shown && !room };
}

/** Whether the panel is showing, in either place: the header button's `aria-pressed`. */
export const shown = (state: SidePanelState, offered: boolean, room: boolean): boolean => {
  const { beside, inPlace } = placement(state, offered, room);
  return beside || inPlace;
};

/** The turn the detective tab is on: the one picked, else the newest. */
export const selectedTurnId = (state: SidePanelState, turns: readonly TracedTurn[]): string | null =>
  state.picked ?? turns[turns.length - 1]?.id ?? null;
