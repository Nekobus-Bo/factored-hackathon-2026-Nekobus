// A hash router for five screens. The hash keeps deep links working behind any static route (the server
// answers every non-API path with the page) and needs no history handling.

import { HandoffRefSchema } from "@pattern-blue/contracts";
import { useEffect, useState } from "react";

export type Route =
  | { name: "queue" }
  | { name: "handoff"; ref: string }
  | { name: "guardrails" }
  | { name: "metrics" }
  | { name: "flows" };

export function parseHash(hash: string): Route {
  const path = hash.replace(/^#/, "").replace(/^\/+/, "").replace(/\/+$/, "");
  const parts = path.split("/");
  if (parts[0] === "guardrails" && parts.length === 1) return { name: "guardrails" };
  if (parts[0] === "metrics" && parts.length === 1) return { name: "metrics" };
  if (parts[0] === "flows" && parts.length === 1) return { name: "flows" };
  if (parts[0] === "handoffs" && parts.length === 2) {
    let ref: string;
    try {
      ref = decodeURIComponent(parts[1] as string);
    } catch {
      return { name: "queue" };
    }
    // A ref becomes part of an API path: anything that is not an opaque token is not a case.
    if (HandoffRefSchema.safeParse(ref).success) return { name: "handoff", ref };
  }
  return { name: "queue" };
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseHash(window.location.hash));
  useEffect(() => {
    const update = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  return route;
}
