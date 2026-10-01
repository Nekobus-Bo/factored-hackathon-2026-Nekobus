import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { startServer } from "../src/server";
import { makeConfig } from "./support/harness";
import { startFakeBankingCore, startFakeOrchestrator } from "./support/fake-upstreams";

const bankingCore = startFakeBankingCore();
const orchestrator = startFakeOrchestrator();
let server: ReturnType<typeof startServer>;
let base: string;

beforeAll(() => {
  const config = makeConfig({
    PORT: "1",
    BANKING_CORE_URL: bankingCore.url,
    ORCHESTRATOR_URL: orchestrator.url,
    ADMIN_API_TOKEN: bankingCore.token,
    AGENT_API_TOKEN: orchestrator.token,
  });
  // Port 0 asks for an ephemeral port; the config only needs to be valid.
  server = startServer({ ...config, port: 0 }, { log: () => {} });
  base = `http://127.0.0.1:${server.port}`;
});
afterAll(() => {
  server.stop(true);
  bankingCore.stop();
  orchestrator.stop();
});

describe("the server over real HTTP", () => {
  test("GET /healthz", async () => {
    const response = await fetch(`${base}/healthz`);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: "ok" });
  });

  test("serves the page at / and under any client route", async () => {
    for (const path of ["/", "/anything/else"]) {
      const response = await fetch(`${base}${path}`);
      expect(response.status).toBe(200);
      expect(response.headers.get("content-type")).toContain("text/html");
      const html = await response.text();
      expect(html).toContain('<div id="root">');
      expect(html).toContain("fonts.googleapis.com");
    }
  });

  test("an unknown path under /api is the BFF's 404, never the page", async () => {
    for (const path of ["/api", "/api/", "/api/nope", "/api/v1/admin/policy-config"]) {
      const response = await fetch(`${base}${path}`);
      expect(response.status, path).toBe(404);
      expect(await response.json()).toEqual({ detail: "not_found" });
    }
  });

  test("login, the cookie and a protected route work end to end", async () => {
    expect((await fetch(`${base}/api/handoffs`)).status).toBe(401);

    const login = await fetch(`${base}/api/session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: "agent@demo.local", password: "demo-only-change-me" }),
    });
    expect(login.status).toBe(204);
    const setCookie = login.headers.get("set-cookie") as string;
    expect(setCookie).toMatch(/HttpOnly/);
    expect(setCookie).toMatch(/SameSite=Strict/);

    const cookie = setCookie.split(";")[0] as string;
    const handoffs = await fetch(`${base}/api/handoffs`, { headers: { Cookie: cookie } });
    expect(handoffs.status).toBe(200);
    expect(((await handoffs.json()) as { items: unknown[] }).items.length).toBeGreaterThan(0);

    // No token of either upstream ever reaches the browser.
    const everything = JSON.stringify([...handoffs.headers.entries()]) + setCookie;
    expect(everything).not.toContain(bankingCore.token);
    expect(everything).not.toContain(orchestrator.token);
  });

  test("a request body over the limit is refused before the BFF reads it", async () => {
    const response = await fetch(`${base}/api/session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: "agent@demo.local", password: "x".repeat(100_000) }),
    });
    expect(response.status).toBe(413);
  });
});

describe("the server process", () => {
  /** A port nobody is using right now. */
  function freePort(): number {
    const probe = Bun.serve({ port: 0, fetch: () => new Response() });
    const { port } = probe;
    probe.stop(true);
    return port as number;
  }

  async function run(env: Record<string, string>) {
    const child = Bun.spawn(["bun", "src/server.ts"], {
      cwd: `${import.meta.dir}/..`,
      env: { PATH: process.env.PATH ?? "", HOME: process.env.HOME ?? "", ...env },
      stdout: "pipe",
      stderr: "pipe",
    });
    return { child, exit: child.exited, stderr: new Response(child.stderr).text() };
  }

  test("refuses to start under APP_ENV=production with the development defaults", async () => {
    const { exit, stderr } = await run({ APP_ENV: "production", PORT: String(freePort()) });
    expect(await exit).toBe(1);
    const message = await stderr;
    expect(message).toContain("refusing to start");
    for (const name of ["ADMIN_API_TOKEN", "AGENT_API_TOKEN", "DEMO_AGENT_PASSWORD", "BACKOFFICE_SESSION_SECRET"]) {
      expect(message).toContain(name);
    }
  });

  test("starts under APP_ENV=production with secrets of its own", async () => {
    const { child } = await run({
      APP_ENV: "production",
      PORT: String(freePort()),
      ADMIN_API_TOKEN: "x-admin",
      AGENT_API_TOKEN: "x-agent",
      DEMO_AGENT_PASSWORD: "x-password",
      BACKOFFICE_SESSION_SECRET: "x-secret-x-secret-x-secret",
    });
    await Bun.sleep(600);
    expect(child.exitCode).toBeNull();
    child.kill();
    await child.exited;
  });
});
