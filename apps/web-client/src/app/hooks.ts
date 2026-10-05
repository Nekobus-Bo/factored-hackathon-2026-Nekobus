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

/** The window is wide enough for the demo panel beside the chat (the same width as the stylesheet's cut). */
export const SIDE_PANEL_QUERY = "(min-width: 920px)";

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
