// The demo panel's state as a pure function: open or not, its tab and the turn picked, and where it sits (beside the
// chat, or in place of it on a narrow window). The transitions the dock cannot show without a DOM.

import { describe, expect, test } from "bun:test";
import {
  effectiveTab,
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
    for (const action of [{ type: "toggle" }, { type: "toggle", tab: "detective" }, { type: "open", turnId: "e2" }] as const) {
      const opened = run(initialSidePanel(), action);
      expect(opened.seen, action.type).toBe(true);
      // closing it, switching tabs, reopening: seen stays
      expect(run(opened, { type: "close" }).seen).toBe(true);
      expect(run(opened, { type: "toggle" }, { type: "toggle" }).seen).toBe(true);
    }
  });

  test("nothing that leaves the panel closed makes it seen", () => {
    const closed = initialSidePanel();
    for (const action of [{ type: "close" }, { type: "tab", tab: "detective" }, { type: "select", turnId: "e2" }, { type: "newTurn" }, { type: "offered", offered: false }, { type: "room", room: false }] as const) {
      expect(run(closed, action).seen, action.type).toBe(false);
    }
    // opened on the detective tab from the start (tests) and then the window narrows: still a visit in which it was open
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

  test("with no room it names the detective tab: it opens that one, whatever the last tab was, and closes it", () => {
    const opened = run(initialSidePanel(), { type: "toggle", tab: "detective" });
    expect(opened).toMatchObject({ open: true, tab: "detective" });
    expect(run(opened, { type: "toggle", tab: "detective" }).open).toBe(false);
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
    const reopened = run(picked, { type: "close" }, { type: "toggle", tab: "detective" });
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

  test("naming the detective tab (the button with no room for the panel) while the panel is open keeps the turn", () => {
    const onTurn = run(initialSidePanel(), { type: "open", turnId: "e2" });
    // with no room the button names the detective tab: closed and opened again from closed it follows the newest turn,
    // while an open panel keeps the one picked
    const viaButton = run(onTurn, { type: "tab", tab: "script" }, { type: "toggle", tab: "detective" });
    expect(viaButton.picked).toBe("e2");
  });

  test("the stepper picks a turn; a new turn puts the tab back on the newest", () => {
    const open = run(initialSidePanel(), { type: "toggle", tab: "detective" }, { type: "select", turnId: "e2" });
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

describe("the window turned narrow", () => {
  test("a panel open on the guide closes: there is no room for it and nothing would show", () => {
    const guide = run(initialSidePanel(), { type: "toggle" });
    expect(run(guide, { type: "room", room: false })).toEqual({ open: false, tab: "script", picked: null, seen: true });
    // and it stays closed when the window widens again
    expect(run(guide, { type: "room", room: false }, { type: "room", room: true }).open).toBe(false);
  });

  test("the detective tab goes on (it shows in place of the chat); wide again, or a closed panel, change nothing", () => {
    const detective = run(initialSidePanel(), { type: "open", turnId: "e2" });
    expect(run(detective, { type: "room", room: false })).toBe(detective);
    expect(run(detective, { type: "room", room: true })).toBe(detective);
    const closed = initialSidePanel();
    expect(run(closed, { type: "room", room: false })).toBe(closed);
  });

  test("the mode turned off at the same time: the detective tab goes to the guide, and then closes", () => {
    const detective = run(initialSidePanel(), { type: "open", turnId: "e2" });
    const after = run(detective, { type: "offered", offered: false }, { type: "room", room: false });
    expect(after.open).toBe(false);
  });
});

describe("where the panel is", () => {
  test("closed, it is nowhere", () => {
    expect(placement(initialSidePanel(), true, true)).toEqual({ beside: false, inPlace: false });
    expect(placement(initialSidePanel(), true, false)).toEqual({ beside: false, inPlace: false });
  });

  test("with room it is beside the chat on either tab; the chat is never replaced", () => {
    for (const tab of ["script", "detective"] as const) {
      expect(placement(initialSidePanel(tab), true, true)).toEqual({ beside: true, inPlace: false });
    }
    expect(placement(initialSidePanel("script"), false, true)).toEqual({ beside: true, inPlace: false });
  });

  test("with no room only the detective tab shows, in place of the chat; the script shows nothing", () => {
    expect(placement(initialSidePanel("detective"), true, false)).toEqual({ beside: false, inPlace: true });
    expect(placement(initialSidePanel("script"), true, false)).toEqual({ beside: false, inPlace: false });
  });

  test("with no room and the mode off, the chat is back", () => {
    expect(placement(initialSidePanel("detective"), false, false)).toEqual({ beside: false, inPlace: false });
  });

  test("the one header button is pressed while the panel shows, in either place, and not otherwise", () => {
    expect(shown(initialSidePanel(), true, true)).toBe(false);
    expect(shown(initialSidePanel("script"), true, true)).toBe(true);
    expect(shown(initialSidePanel("detective"), true, true)).toBe(true);
    // with no room only the detective tab shows
    expect(shown(initialSidePanel("detective"), true, false)).toBe(true);
    expect(shown(initialSidePanel("script"), true, false)).toBe(false);
    // the mode off: the detective tab reads as the script, which shows beside the chat and nowhere else
    expect(shown(initialSidePanel("detective"), false, true)).toBe(true);
    expect(shown(initialSidePanel("detective"), false, false)).toBe(false);
  });
});
