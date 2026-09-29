// A BFF wired to fake upstreams, and a small client for it.

import { createBff, type Bff } from "../../src/bff/app";
import { DEVELOPMENT_DEFAULTS, loadConfig, type Config } from "../../src/bff/config";
import { startFakeBankingCore, startFakeOrchestrator, type FakeService } from "./fake-upstreams";

export interface Harness {
  config: Config;
  bff: Bff;
  bankingCore: FakeService;
  orchestrator: FakeService;
  /** Send a request to the BFF. `cookie` is the `Cookie` header value; JSON bodies get the JSON content type. */
  request(
    path: string,
    init?: { method?: string; body?: unknown; cookie?: string | null; headers?: Record<string, string>; contentType?: string | null },
  ): Promise<Response>;
  /** Log in as the demo agent and return the session cookie as the browser would send it. */
  login(): Promise<string>;
  stop(): void;
}

export function makeConfig(overrides: Record<string, string | undefined> = {}): Config {
  return loadConfig({
    APP_ENV: "development",
    DEMO_AGENT_EMAIL: DEVELOPMENT_DEFAULTS.agentEmail,
    DEMO_AGENT_PASSWORD: DEVELOPMENT_DEFAULTS.agentPassword,
    BACKOFFICE_SESSION_SECRET: "test-session-secret",
    ...overrides,
  });
}

export function makeHarness(options: { now?: () => number; env?: Record<string, string | undefined> } = {}): Harness {
  const bankingCore = startFakeBankingCore();
  const orchestrator = startFakeOrchestrator();
  const config = makeConfig({
    BANKING_CORE_URL: bankingCore.url,
    ORCHESTRATOR_URL: orchestrator.url,
    ADMIN_API_TOKEN: bankingCore.token,
    AGENT_API_TOKEN: orchestrator.token,
    UPSTREAM_TIMEOUT_MS: "3000",
    ...options.env,
  });
  const bff = createBff(config, { now: options.now, log: () => {} });

  async function request(path: string, init: Parameters<Harness["request"]>[1] = {}) {
    const method = init.method ?? "GET";
    const headers: Record<string, string> = { ...init.headers };
    if (init.cookie) headers.Cookie = init.cookie;
    const contentType = init.contentType === undefined ? (method === "GET" ? null : "application/json") : init.contentType;
    if (contentType) headers["Content-Type"] = contentType;
    const body = init.body === undefined ? undefined : typeof init.body === "string" ? init.body : JSON.stringify(init.body);
    return bff.handle(new Request(`http://backoffice.test${path}`, { method, headers, body }));
  }

  async function login() {
    const response = await request("/api/session", {
      method: "POST",
      body: { email: config.agentEmail, password: config.agentPassword },
    });
    if (response.status !== 204) throw new Error(`login failed: ${response.status}`);
    const setCookie = response.headers.get("set-cookie") ?? "";
    return setCookie.split(";")[0] as string;
  }

  return {
    config,
    bff,
    bankingCore,
    orchestrator,
    request,
    login,
    stop() {
      bankingCore.stop();
      orchestrator.stop();
    },
  };
}
