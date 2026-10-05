import { useEffect, useState, useSyncExternalStore } from "react";

/** The wall clock, ticking every `intervalMs` while `intervalMs` is a number. */
export function useNow(intervalMs: number | null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (intervalMs === null) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

const DARK_QUERY = "(prefers-color-scheme: dark)";

/** Whether the browser prefers dark: what `system` means for the theme switch. False when it cannot say. */
export function useSystemDark(): boolean {
  return useSyncExternalStore(
    (notify) => {
      if (typeof window === "undefined" || !window.matchMedia) return () => {};
      const query = window.matchMedia(DARK_QUERY);
      query.addEventListener("change", notify);
      return () => query.removeEventListener("change", notify);
    },
    () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(DARK_QUERY).matches : false),
    () => false,
  );
}

/**
 * There is room for the demo panel beside the chat: 920px wide and 500px tall. The complement of the stylesheet's "no room"
 * query in `local.css`, `(max-width: 919.98px), (max-height: 499.98px)` (decimals so a fractional size is on one side or the
 * other, without range syntax, which older iOS drops), where the chat takes the whole screen and the panel replaces it:
 * change them together.
 */
export const SIDE_PANEL_QUERY = "(min-width: 920px) and (min-height: 500px)";

/** Whether there is room for the demo panel beside the chat. True on the server and where the browser cannot say. */
export function useSidePanelRoom(): boolean {
  return useSyncExternalStore(
    (notify) => {
      if (typeof window === "undefined" || !window.matchMedia) return () => {};
      const query = window.matchMedia(SIDE_PANEL_QUERY);
      query.addEventListener("change", notify);
      return () => query.removeEventListener("change", notify);
    },
    () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(SIDE_PANEL_QUERY).matches : true),
    () => true,
  );
}
