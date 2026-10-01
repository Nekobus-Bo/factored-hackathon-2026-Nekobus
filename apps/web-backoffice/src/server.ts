// The back-office server: the bundle, `GET /healthz` and the same-origin BFF under `/api`.
//
//   bun --hot src/server.ts        development (HTML import, hot reload)
//   bun run build && bun run start production (the bundle and this server, built by `bun build --target=bun`)
//
// The browser talks only to this origin. The orchestrator and banking-core are reached from here, with
// tokens that never leave this process.

import { ConfigError, loadConfig, type Config } from "./bff/config";
import { createBff, type BffDeps } from "./bff/app";
import index from "./index.html";

/** Requests are small JSON documents; the largest is an agent message of 2000 characters. */
export const MAX_REQUEST_BODY_BYTES = 64 * 1024;

/** The most upstream calls one route makes in a row: claiming a handoff (claim, conversation, takeover). */
export const MAX_SEQUENTIAL_UPSTREAM_CALLS = 3;

/** Bun's ceiling for `idleTimeout`, in seconds. */
const BUN_MAX_IDLE_TIMEOUT_SECONDS = 255;

/**
 * How long the connection to the browser may wait for an answer. Bun's default (10 s) is no longer than one
 * upstream call may take, so a slow upstream (a cold start) dropped the connection before the BFF answered.
 * This covers the longest route at its upstream timeout, plus a margin, within Bun's ceiling.
 */
export function idleTimeoutSeconds(upstreamTimeoutMs: number): number {
  const longestRouteSeconds = Math.ceil((upstreamTimeoutMs * MAX_SEQUENTIAL_UPSTREAM_CALLS) / 1000);
  return Math.min(BUN_MAX_IDLE_TIMEOUT_SECONDS, longestRouteSeconds + 5);
}

export function startServer(config: Config, deps: BffDeps = {}) {
  const bff = createBff(config, deps);
  const api = (req: Request) => bff.handle(req);

  return Bun.serve({
    port: config.port,
    idleTimeout: idleTimeoutSeconds(config.upstreamTimeoutMs),
    maxRequestBodySize: MAX_REQUEST_BODY_BYTES,
    routes: {
      // Liveness only: it does not look at the upstreams, so the container is healthy as soon as it serves.
      "/healthz": { GET: () => Response.json({ status: "ok" }, { headers: { "Cache-Control": "no-store" } }) },
      // A closed list lives in the BFF; anything else under /api is its 404, never the page.
      "/api": api,
      "/api/*": api,
      "/*": index,
    },
  });
}

if (import.meta.main) {
  let config: Config;
  try {
    config = loadConfig();
  } catch (error) {
    if (error instanceof ConfigError) {
      console.error(`web-backoffice: refusing to start, ${error.message}`);
      process.exit(1);
    }
    throw error;
  }
  const server = startServer(config);
  console.log(`web-backoffice: listening on ${server.url} (APP_ENV=${config.appEnv})`);
}
