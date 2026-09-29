// The web-client server: the page, `GET /healthz` and the BFF (`/api/*`).
//
//   bun --hot src/server.ts     development (bun run dev)
//   bun dist/server.js          production, after bun run build (bun run start)

import { createBff } from "./api/bff";
import { loadConfig, type Config } from "./config";
import index from "./index.html";

export interface StartOptions extends Config {
  /** Injected in tests. */
  fetch?: typeof fetch;
  log?: (line: string) => void;
  development?: boolean;
}

export function startServer(options: StartOptions) {
  const bff = createBff({
    orchestratorUrl: options.orchestratorUrl,
    fetch: options.fetch,
    log: options.log,
  });

  return Bun.serve({
    port: options.port,
    development: options.development ?? process.env.NODE_ENV !== "production",
    // A turn runs the LLM and the tools: the connection to the browser waits for it (Bun's default is 10 s).
    idleTimeout: 200,
    // The longest message is 2000 characters; this leaves room for JSON and multi-byte text, nothing more.
    maxRequestBodySize: 64 * 1024,
    routes: {
      "/": index,
      "/healthz": () => Response.json({ status: "ok" }, { headers: { "Cache-Control": "no-store" } }),
    },
    // Everything else: `/api` and below belong to the BFF (which answers its own 404 and 405), the rest is a 404.
    fetch(req, server) {
      const { pathname } = new URL(req.url);
      if (pathname === "/api" || pathname.startsWith("/api/")) {
        return bff.handle(req, server.requestIP(req)?.address ?? null);
      }
      return new Response("Not found", { status: 404, headers: { "Content-Type": "text/plain" } });
    },
  });
}

if (import.meta.main) {
  const config = loadConfig();
  const server = startServer(config);
  console.log(`web-client listening on ${server.url.href} (orchestrator: ${config.orchestratorUrl})`);
}
