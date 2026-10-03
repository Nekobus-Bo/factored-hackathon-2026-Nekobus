import { describe, expect, test } from "bun:test";
import {
  SESSION_COOKIE,
  cookieValue,
  credentialsMatch,
  readSession,
  safeEqual,
  sessionClearCookie,
  sessionSetCookie,
  signSession,
  type Compare,
} from "../src/bff/session";
import { makeHarness } from "./support/harness";

const SECRET = "unit-test-secret";
const NOW = Date.UTC(2026, 8, 29, 10, 0, 0);
const payload = { agent_ref: "agent@demo.local", exp: Math.floor(NOW / 1000) + 3600 };

const swapSegment = (value: string, index: 0 | 1, replacement: string) => {
  const parts = value.split(".");
  parts[index] = replacement;
  return parts.join(".");
};

describe("session cookie", () => {
  test("a signed session reads back", () => {
    expect(readSession(signSession(payload, SECRET), SECRET, NOW)).toEqual(payload);
  });

  test("the value has two base64url parts: the payload and its HMAC-SHA256", () => {
    const value = signSession(payload, SECRET);
    const [body, signature] = value.split(".") as [string, string];
    expect(value.split(".")).toHaveLength(2);
    expect(JSON.parse(Buffer.from(body, "base64url").toString())).toEqual(payload);
    expect(Buffer.from(signature, "base64url")).toHaveLength(32);
    const expected = new Bun.CryptoHasher("sha256", SECRET).update(body).digest("base64url");
    expect(signature).toBe(expected);
  });

  test("a tampered payload is refused, even one that would extend the session", () => {
    const value = signSession(payload, SECRET);
    const forged = Buffer.from(JSON.stringify({ ...payload, exp: payload.exp + 86_400 })).toString("base64url");
    expect(readSession(swapSegment(value, 0, forged), SECRET, NOW)).toBeNull();
    const otherAgent = Buffer.from(JSON.stringify({ ...payload, agent_ref: "root@demo.local" })).toString("base64url");
    expect(readSession(swapSegment(value, 0, otherAgent), SECRET, NOW)).toBeNull();
  });

  test("a tampered or truncated signature is refused", () => {
    const value = signSession(payload, SECRET);
    const signature = value.split(".")[1] as string;
    const flipped = (signature[0] === "A" ? "B" : "A") + signature.slice(1);
    expect(readSession(swapSegment(value, 1, flipped), SECRET, NOW)).toBeNull();
    expect(readSession(swapSegment(value, 1, signature.slice(0, -4)), SECRET, NOW)).toBeNull();
    expect(readSession(swapSegment(value, 1, ""), SECRET, NOW)).toBeNull();
  });

  test("a cookie signed with another secret is refused", () => {
    expect(readSession(signSession(payload, "another-secret"), SECRET, NOW)).toBeNull();
  });

  test("an expired session is refused, and the expiry second itself is already too late", () => {
    const value = signSession(payload, SECRET);
    expect(readSession(value, SECRET, (payload.exp - 1) * 1000)).not.toBeNull();
    expect(readSession(value, SECRET, payload.exp * 1000)).toBeNull();
    expect(readSession(value, SECRET, (payload.exp + 60) * 1000)).toBeNull();
  });

  test.each([undefined, null, "", "garbage", "a.b.c", ".", "abc."])("garbage is no session: %p", (value) => {
    expect(readSession(value as string | undefined, SECRET, NOW)).toBeNull();
  });

  test("a validly signed payload of the wrong shape is refused", () => {
    for (const wrong of [{ agent_ref: "not an email", exp: payload.exp }, { agent_ref: payload.agent_ref }, { agent_ref: payload.agent_ref, exp: "soon" }, { ...payload, extra: 1 }, "text"]) {
      const body = Buffer.from(JSON.stringify(wrong)).toString("base64url");
      const signature = new Bun.CryptoHasher("sha256", SECRET).update(body).digest("base64url");
      expect(readSession(`${body}.${signature}`, SECRET, NOW)).toBeNull();
    }
    const notJson = Buffer.from("not json").toString("base64url");
    const signature = new Bun.CryptoHasher("sha256", SECRET).update(notJson).digest("base64url");
    expect(readSession(`${notJson}.${signature}`, SECRET, NOW)).toBeNull();
  });

  test("Set-Cookie is HttpOnly, SameSite=Strict, Path=/ and Secure only in production", () => {
    const development = sessionSetCookie("value", { secure: false, maxAgeSeconds: 28_800 });
    expect(development).toBe(`${SESSION_COOKIE}=value; Path=/; HttpOnly; SameSite=Strict; Max-Age=28800`);
    const production = sessionSetCookie("value", { secure: true, maxAgeSeconds: 28_800 });
    expect(production).toEndWith("; Secure");
    expect(production).toContain("HttpOnly");
    expect(production).toContain("SameSite=Strict");
    expect(production).toContain("Path=/");
    expect(sessionClearCookie({ secure: true })).toContain("Max-Age=0");
  });

  test("reads one cookie out of a Cookie header", () => {
    expect(cookieValue(`a=1; ${SESSION_COOKIE}=abc.def; b=2`, SESSION_COOKIE)).toBe("abc.def");
    expect(cookieValue("a=1", SESSION_COOKIE)).toBeUndefined();
    expect(cookieValue(null, SESSION_COOKIE)).toBeUndefined();
    expect(cookieValue(`x${SESSION_COOKIE}=nope`, SESSION_COOKIE)).toBeUndefined();
  });
});

describe("constant-time comparison", () => {
  test("safeEqual is equality, for any lengths", () => {
    expect(safeEqual("secret", "secret")).toBe(true);
    expect(safeEqual("secret", "secreT")).toBe(false);
    expect(safeEqual("secret", "secret-and-more")).toBe(false);
    expect(safeEqual("", "secret")).toBe(false);
    expect(safeEqual("", "")).toBe(true);
    expect(safeEqual("ñandú", "ñandú")).toBe(true);
  });

  test("a login compares both fields even when the first one is wrong", () => {
    const calls: [string, string][] = [];
    const spy: Compare = (supplied, expected) => {
      calls.push([supplied, expected]);
      return safeEqual(supplied, expected);
    };
    const expected = { email: "agent@demo.local", password: "right-password" };

    expect(credentialsMatch({ email: "other@demo.local", password: "right-password" }, expected, spy)).toBe(false);
    expect(calls).toEqual([
      ["other@demo.local", "agent@demo.local"],
      ["right-password", "right-password"],
    ]);

    calls.length = 0;
    expect(credentialsMatch({ email: "agent@demo.local", password: "wrong" }, expected, spy)).toBe(false);
    expect(calls).toHaveLength(2);

    calls.length = 0;
    expect(credentialsMatch({ email: "agent@demo.local", password: "right-password" }, expected, spy)).toBe(true);
  });

  test("the e-mail is case-insensitive, the password is not", () => {
    const expected = { email: "agent@demo.local", password: "Right-Password" };
    expect(credentialsMatch({ email: " Agent@Demo.Local ", password: "Right-Password" }, expected)).toBe(true);
    expect(credentialsMatch({ email: "agent@demo.local", password: "right-password" }, expected)).toBe(false);
  });

  test("the BFF's login route goes through the injected comparison for both fields", async () => {
    const calls: string[] = [];
    const { createBff } = await import("../src/bff/app");
    const { makeConfig } = await import("./support/harness");
    const bff = createBff(makeConfig(), {
      log: () => {},
      compare: (supplied, expected) => {
        calls.push(expected);
        return safeEqual(supplied, expected);
      },
    });
    const response = await bff.handle(
      new Request("http://backoffice.test/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: "nobody@example.com", password: "nope" }),
      }),
    );
    expect(response.status).toBe(401);
    expect(calls).toEqual(["agent@demo.local", "demo-only-change-me"]);
  });

  test("with extra agents, every account is compared, even after a match", async () => {
    const calls: string[] = [];
    const { createBff } = await import("../src/bff/app");
    const { makeConfig } = await import("./support/harness");
    const bff = createBff(makeConfig({ DEMO_EXTRA_AGENTS: '{"judge1@demo.local": "pw-one", "judge2@demo.local": "pw-two"}' }), {
      log: () => {},
      compare: (supplied, expected) => {
        calls.push(expected);
        return safeEqual(supplied, expected);
      },
    });
    const response = await bff.handle(
      new Request("http://backoffice.test/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: "agent@demo.local", password: "demo-only-change-me" }),
      }),
    );
    expect(response.status).toBe(204);
    expect(calls).toEqual(["agent@demo.local", "demo-only-change-me", "judge1@demo.local", "pw-one", "judge2@demo.local", "pw-two"]);
  });
});

describe("login and logout through the BFF", () => {
  test("a good login answers 204 and sets the cookie the session route accepts", async () => {
    const harness = makeHarness({ now: () => NOW });
    try {
      const response = await harness.request("/api/session", { method: "POST", body: { email: "agent@demo.local", password: "demo-only-change-me" } });
      expect(response.status).toBe(204);
      expect(await response.text()).toBe("");
      const setCookie = response.headers.get("set-cookie") as string;
      expect(setCookie).toContain("HttpOnly");
      expect(setCookie).toContain("SameSite=Strict");
      expect(setCookie).toContain("Path=/");
      expect(setCookie).toContain("Max-Age=28800");
      expect(setCookie).not.toContain("Secure");

      const cookie = setCookie.split(";")[0] as string;
      const value = cookie.slice(SESSION_COOKIE.length + 1);
      expect(readSession(value, harness.config.sessionSecret, NOW)).toEqual({ agent_ref: "agent@demo.local", exp: Math.floor(NOW / 1000) + 28_800 });

      const session = await harness.request("/api/session", { cookie });
      expect(session.status).toBe(200);
      expect(await session.json()).toEqual({ agent_ref: "agent@demo.local" });
    } finally {
      harness.stop();
    }
  });

  test("the cookie is Secure under APP_ENV=production", async () => {
    const harness = makeHarness({
      env: {
        APP_ENV: "production",
        DEMO_AGENT_PASSWORD: "a-real-password",
        BACKOFFICE_SESSION_SECRET: "a-random-session-secret",
        ADMIN_API_TOKEN: "real-admin",
        AGENT_API_TOKEN: "real-agent",
      },
    });
    try {
      const response = await harness.request("/api/session", { method: "POST", body: { email: "agent@demo.local", password: "a-real-password" } });
      expect(response.status).toBe(204);
      expect(response.headers.get("set-cookie")).toEndWith("; Secure");
    } finally {
      harness.stop();
    }
  });

  test.each([
    ["a wrong password", { email: "agent@demo.local", password: "wrong" }],
    ["an unknown e-mail", { email: "someone@else.example", password: "demo-only-change-me" }],
  ])("%s is 401 with no cookie", async (_label, body) => {
    const harness = makeHarness();
    try {
      const response = await harness.request("/api/session", { method: "POST", body });
      expect(response.status).toBe(401);
      expect(response.headers.get("set-cookie")).toBeNull();
      expect(await response.json()).toEqual({ detail: "invalid_credentials" });
    } finally {
      harness.stop();
    }
  });

  describe("with extra agents", () => {
    const env = { DEMO_EXTRA_AGENTS: '{"Judge1@demo.local": "pw-one", "judge2@demo.local": "pw-two"}' };

    test("each one logs in as itself, spelled the configured way", async () => {
      const harness = makeHarness({ env });
      try {
        for (const [email, password, agentRef] of [
          ["judge1@demo.local", "pw-one", "Judge1@demo.local"],
          ["judge2@demo.local", "pw-two", "judge2@demo.local"],
          ["agent@demo.local", "demo-only-change-me", "agent@demo.local"],
        ] as const) {
          const response = await harness.request("/api/session", { method: "POST", body: { email, password } });
          expect(response.status).toBe(204);
          const cookie = (response.headers.get("set-cookie") as string).split(";")[0] as string;
          const session = await harness.request("/api/session", { cookie });
          expect(await session.json()).toEqual({ agent_ref: agentRef });
        }
      } finally {
        harness.stop();
      }
    });

    test.each([
      ["another judge's password", { email: "judge1@demo.local", password: "pw-two" }],
      ["the demo agent's password", { email: "judge1@demo.local", password: "demo-only-change-me" }],
      ["a judge's password for the demo agent", { email: "agent@demo.local", password: "pw-one" }],
    ])("%s is 401", async (_label, body) => {
      const harness = makeHarness({ env });
      try {
        const response = await harness.request("/api/session", { method: "POST", body });
        expect(response.status).toBe(401);
        expect(response.headers.get("set-cookie")).toBeNull();
      } finally {
        harness.stop();
      }
    });
  });

  test("the session belongs to the configured agent, spelled the configured way", async () => {
    const harness = makeHarness();
    try {
      const response = await harness.request("/api/session", { method: "POST", body: { email: "AGENT@Demo.Local", password: "demo-only-change-me" } });
      expect(response.status).toBe(204);
      const cookie = (response.headers.get("set-cookie") as string).split(";")[0] as string;
      expect(await (await harness.request("/api/session", { cookie })).json()).toEqual({ agent_ref: "agent@demo.local" });
    } finally {
      harness.stop();
    }
  });

  test("a malformed login is 422, and an unknown key is refused", async () => {
    const harness = makeHarness();
    try {
      expect((await harness.request("/api/session", { method: "POST", body: { email: "no-at-sign", password: "x" } })).status).toBe(422);
      expect((await harness.request("/api/session", { method: "POST", body: { email: "a@b.c", password: "" } })).status).toBe(422);
      expect((await harness.request("/api/session", { method: "POST", body: { email: "a@b.c", password: "x", admin: true } })).status).toBe(422);
      expect((await harness.request("/api/session", { method: "POST", body: "{not json" })).status).toBe(400);
    } finally {
      harness.stop();
    }
  });

  test("an expired session is 401 on every route", async () => {
    let now = NOW;
    const harness = makeHarness({ now: () => now });
    try {
      const cookie = await harness.login();
      expect((await harness.request("/api/session", { cookie })).status).toBe(200);
      now += 8 * 60 * 60 * 1000 - 1000;
      expect((await harness.request("/api/session", { cookie })).status).toBe(200);
      now += 1000;
      expect((await harness.request("/api/session", { cookie })).status).toBe(401);
      expect((await harness.request("/api/handoffs", { cookie })).status).toBe(401);
    } finally {
      harness.stop();
    }
  });

  test("logout clears the cookie", async () => {
    const harness = makeHarness();
    try {
      const cookie = await harness.login();
      const response = await harness.request("/api/session", { method: "DELETE", cookie });
      expect(response.status).toBe(204);
      const cleared = response.headers.get("set-cookie") as string;
      expect(cleared).toContain(`${SESSION_COOKIE}=;`);
      expect(cleared).toContain("Max-Age=0");
      expect((await harness.request("/api/session", { method: "DELETE" })).status).toBe(401);
    } finally {
      harness.stop();
    }
  });
});
