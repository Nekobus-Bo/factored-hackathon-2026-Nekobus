// The demo panel's state as a pure function: open or not, its tab and the turn picked, and where it sits (beside the
// chat, or in place of it when there is no room). The transitions the dock cannot show without a DOM.

import { describe, expect, test } from "bun:test";
import {
  effectiveTab,
  focusAfterGuide,
  focusesOnRequest,
  initialSidePanel,
  placement,
  selectedTurnId,
  shown,
  sidePanelReducer,
  type SidePanelAction,
  type SidePanelState,
} from "../src/app/chat/detective-view";
import type { TracedTurn } from "../src/app/chat/trace-model";
import { TRACE } from "./fixtures";

const run = (state: SidePanelState, ...actions: SidePanelAction[]) => actions.reduce(sidePanelReducer, state);
const turns: TracedTurn[] = [
  { id: "e2", n: 1, trace: TRACE },
  { id: "e6", n: 3, trace: TRACE },
];

describe("the header button has been seen once the panel has been open", () => {
  test("a visit starts unseen; the first opening, by whatever way, makes it seen for good", () => {
    expect(initialSidePanel().seen).toBe(false);
    for (const action of [{ type: "toggle" }, { type: "open", turnId: "e2" }] as const) {
      const opened = run(initialSidePanel(), action);
      expect(opened.seen, action.type).toBe(true);
      // closing it, switching tabs, reopening: seen stays
      expect(run(opened, { type: "close" }).seen).toBe(true);
      expect(run(opened, { type: "toggle" }, { type: "toggle" }).seen).toBe(true);
    }
  });

  test("nothing that leaves the panel closed makes it seen", () => {
    const closed = initialSidePanel();
    for (const action of [{ type: "close" }, { type: "tab", tab: "detective" }, { type: "select", turnId: "e2" }, { type: "newTurn" }, { type: "offered", offered: false }, { type: "guideUsed" }] as const) {
      expect(run(closed, action).seen, action.type).toBe(false);
    }
    // opened from the start (tests) and then used with no room: still a visit in which it was open
    expect(initialSidePanel("script").seen).toBe(true);
  });
});

describe("the one button", () => {
  test("it opens the panel on the tab last used in the visit, the guide the first time, and closes it", () => {
    const first = run(initialSidePanel(), { type: "toggle" });
    expect(first).toEqual({ open: true, tab: "script", picked: null, seen: true });
    expect(run(first, { type: "toggle" }).open).toBe(false);
    // the tab the visit ended on is the one that comes back
    const onDetective = run(first, { type: "tab", tab: "detective" }, { type: "toggle" }, { type: "toggle" });
    expect(onDetective).toMatchObject({ open: true, tab: "detective" });
    const backOnGuide = run(onDetective, { type: "tab", tab: "script" }, { type: "toggle" }, { type: "toggle" });
    expect(backOnGuide).toMatchObject({ open: true, tab: "script" });
  });

  test("it opens the panel on the tab last used at any width, so it takes no tab of its own: with no room both tabs show", () => {
    // the same transitions whatever the room: there is no room in the state, the place is derived
    const onDetective = run(initialSidePanel(), { type: "toggle" }, { type: "tab", tab: "detective" }, { type: "toggle" }, { type: "toggle" });
    expect(onDetective).toMatchObject({ open: true, tab: "detective" });
    for (const room of [true, false]) {
      expect(placement(onDetective, room)).toEqual(room ? { beside: true, inPlace: false } : { beside: false, inPlace: true });
      expect(placement(run(onDetective, { type: "tab", tab: "script" }), room)).toEqual(room ? { beside: true, inPlace: false } : { beside: false, inPlace: true });
    }
  });
});

describe("opening and closing the panel", () => {
  test("every visit starts closed, on the script, with no turn picked", () => {
    expect(initialSidePanel()).toEqual({ open: false, tab: "script", picked: null, seen: false });
    expect(initialSidePanel("detective")).toEqual({ open: true, tab: "detective", picked: null, seen: true });
  });

  test("the header button opens the panel and the same button closes it", () => {
    const guide = run(initialSidePanel(), { type: "toggle" });
    expect(guide).toEqual({ open: true, tab: "script", picked: null, seen: true });
    expect(run(guide, { type: "toggle" }).open).toBe(false);
  });

  test("opened from closed, the detective tab follows the newest turn; the one picked before is forgotten", () => {
    const picked = run(initialSidePanel(), { type: "open", turnId: "e2" });
    const reopened = run(picked, { type: "close" }, { type: "toggle" });
    expect(reopened.picked).toBeNull();
    expect(selectedTurnId(reopened, turns)).toBe("e6");
  });

  test("closing (the way back on a narrow window, or Escape) changes nothing else, and closing a closed panel does nothing", () => {
    const open = run(initialSidePanel(), { type: "open", turnId: "e2" });
    expect(run(open, { type: "close" })).toEqual({ open: false, tab: "detective", picked: "e2", seen: true });
    const closed = initialSidePanel();
    expect(run(closed, { type: "close" })).toBe(closed);
  });
});

describe("the control under a reply", () => {
  test("opens the panel on the detective tab with that turn, from closed or from the script tab", () => {
    for (const before of [initialSidePanel(), initialSidePanel("script"), run(initialSidePanel(), { type: "toggle" })]) {
      const after = run(before, { type: "open", turnId: "e2" });
      expect(after).toEqual({ open: true, tab: "detective", picked: "e2", seen: true });
      expect(selectedTurnId(after, turns)).toBe("e2");
    }
  });
});

describe("the tabs", () => {
  test("switching tabs keeps the turn picked, and only the tab changes", () => {
    const onTurn = run(initialSidePanel(), { type: "open", turnId: "e2" });
    const onScript = run(onTurn, { type: "tab", tab: "script" });
    expect(onScript).toEqual({ open: true, tab: "script", picked: "e2", seen: true });
    const back = run(onScript, { type: "tab", tab: "detective" });
    expect(back).toEqual(onTurn);
    expect(selectedTurnId(back, turns)).toBe("e2");
    // the same tab again is the same state
    expect(run(onTurn, { type: "tab", tab: "detective" })).toBe(onTurn);
  });

  test("an open panel keeps the turn picked whichever way the tabs go, and the button only opens and closes", () => {
    const onTurn = run(initialSidePanel(), { type: "open", turnId: "e2" });
    expect(run(onTurn, { type: "tab", tab: "script" }, { type: "tab", tab: "detective" }).picked).toBe("e2");
    // closed and opened again from closed it follows the newest turn
    expect(run(onTurn, { type: "toggle" }, { type: "toggle" }).picked).toBeNull();
  });

  test("the stepper picks a turn; a new turn puts the tab back on the newest", () => {
    const open = run(initialSidePanel("detective"), { type: "select", turnId: "e2" });
    expect(selectedTurnId(open, turns)).toBe("e2");
    expect(selectedTurnId(run(open, { type: "newTurn" }), turns)).toBe("e6");
    expect(run(initialSidePanel(), { type: "newTurn" })).toEqual(initialSidePanel());
  });
});

describe("the mode turned off", () => {
  test("the panel goes to the guide and stays open; a later 'on' does not bring the detective tab back", () => {
    const open = run(initialSidePanel(), { type: "open", turnId: "e2" });
    const off = run(open, { type: "offered", offered: false });
    expect(off).toMatchObject({ open: true, tab: "script" });
    expect(run(off, { type: "offered", offered: true })).toBe(off);
    // 'on', or 'off' with the guide showing, changes nothing
    expect(run(open, { type: "offered", offered: true })).toBe(open);
    const guide = run(initialSidePanel(), { type: "toggle" });
    expect(run(guide, { type: "offered", offered: false })).toBe(guide);
  });

  test("while the answer is still off the detective tab reads as the script", () => {
    const open = initialSidePanel("detective");
    expect(effectiveTab(open, false)).toBe("script");
    expect(effectiveTab(open, true)).toBe("detective");
  });
});

describe("the guide was used (a script picked, a line sent or copied)", () => {
  test("in place of the chat the panel closes, to show the chat (beside the chat the dock does not dispatch it: nothing closes there)", () => {
    const open = run(initialSidePanel(), { type: "toggle" });
    expect(run(open, { type: "guideUsed" })).toEqual({ open: false, tab: "script", picked: null, seen: true });
    // a closed panel stays as it is
    const closed = initialSidePanel();
    expect(run(closed, { type: "guideUsed" })).toBe(closed);
  });

  test("it keeps the tab and the turn: the panel opens again where it was", () => {
    const detective = run(initialSidePanel(), { type: "open", turnId: "e2" }, { type: "tab", tab: "script" });
    const used = run(detective, { type: "guideUsed" });
    expect(used).toMatchObject({ open: false, tab: "script", picked: "e2" });
    expect(run(used, { type: "tab", tab: "detective" })).toMatchObject({ tab: "detective", picked: "e2" });
  });

  test("where the focus goes: a copy to the composer; a pick or a send to the composer if it is free beside the chat, to the log in place of it", () => {
    expect(focusAfterGuide("copy", true)).toBe("composer");
    expect(focusAfterGuide("copy", false)).toBe("composer");
    for (const use of ["pick", "send"] as const) {
      expect(focusAfterGuide(use, true)).toBe("composer-if-free");
      expect(focusAfterGuide(use, false)).toBe("log");
    }
  });
});

describe("the hero's button asking for the composer", () => {
  test("only when the counter moved and the chat was already open and is: an opening click is the opening's own focus, not given twice", () => {
    expect(focusesOnRequest(0, 1, true, true)).toBe(true);
    expect(focusesOnRequest(1, 2, true, true)).toBe(true);
    // the chat was closed and the same click opened it: the open effect focuses, this does not
    expect(focusesOnRequest(0, 1, false, true)).toBe(false);
    // nothing asked (a render for another reason), or the chat is closed
    expect(focusesOnRequest(1, 1, true, true)).toBe(false);
    expect(focusesOnRequest(1, 2, true, false)).toBe(false);
    expect(focusesOnRequest(1, 2, false, false)).toBe(false);
  });
});

describe("the mode turned off in either place", () => {
  test("the mode turned off at the same time: the detective tab goes to the guide and the panel stays open, in either place", () => {
    const detective = run(initialSidePanel(), { type: "open", turnId: "e2" });
    const after = run(detective, { type: "offered", offered: false });
    expect(after).toMatchObject({ open: true, tab: "script" });
    for (const room of [true, false]) expect(placement(after, room)).toEqual(room ? { beside: true, inPlace: false } : { beside: false, inPlace: true });
  });
});

describe("where the panel is", () => {
  test("closed, it is nowhere", () => {
    expect(placement(initialSidePanel(), true)).toEqual({ beside: false, inPlace: false });
    expect(placement(initialSidePanel(), false)).toEqual({ beside: false, inPlace: false });
  });

  test("with room it is beside the chat on either tab; the chat is never replaced", () => {
    for (const tab of ["script", "detective"] as const) {
      expect(placement(initialSidePanel(tab), true)).toEqual({ beside: true, inPlace: false });
    }
  });

  test("with no room it is in place of the chat on either tab", () => {
    for (const tab of ["script", "detective"] as const) {
      expect(placement(initialSidePanel(tab), false)).toEqual({ beside: false, inPlace: true });
    }
  });

  test("the one header button is pressed while the panel is open, in either place, on either tab, and not otherwise", () => {
    expect(shown(initialSidePanel())).toBe(false);
    expect(shown(initialSidePanel("script"))).toBe(true);
    expect(shown(initialSidePanel("detective"))).toBe(true);
  });
});
