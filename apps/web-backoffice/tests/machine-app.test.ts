import { describe, expect, test } from "bun:test";
import { createActor, waitFor } from "xstate";
import { createApi } from "../src/api/client";
import { THEME_STORAGE_KEY, appMachine, readStoredTheme, type RootLike, type StorageLike } from "../src/machines/app";
import { fakeFetch, json, noContent } from "./support/fake-fetch";

class FakeRoot implements RootLike {
  attributes = new Map<string, string>();
  setAttribute(name: string, value: string) {
    this.attributes.set(name, value);
  }
  removeAttribute(name: string) {
    this.attributes.delete(name);
  }
}

class FakeStorage implements StorageLike {
  data = new Map<string, string>();
  getItem(key: string) {
    return this.data.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.data.set(key, value);
  }
  removeItem(key: string) {
    this.data.delete(key);
  }
}

const throwingStorage: StorageLike = {
  getItem() {
    throw new Error("storage is blocked");
  },
  setItem() {
    throw new Error("storage is blocked");
  },
  removeItem() {
    throw new Error("storage is blocked");
  },
};

function start(routes: Parameters<typeof fakeFetch>[0], options: { storage?: StorageLike | null; root?: RootLike } = {}) {
  const network = fakeFetch(routes);
  const root = options.root ?? new FakeRoot();
  // The 401 hook is wired the way main.tsx wires it: to the machine itself.
  const holder: { actor?: ReturnType<typeof createActor<typeof appMachine>> } = {};
  const api = createApi(network.fetch, { onUnauthorized: () => holder.actor?.send({ type: "SESSION.EXPIRED" }) });
  const actor = createActor(appMachine, { input: { api, storage: options.storage === undefined ? new FakeStorage() : options.storage, root } });
  holder.actor = actor;
  actor.start();
  return { actor, network, root };
}

const loggedIn = { "GET /api/session": () => json({ agent_ref: "agent@demo.local" }) };
const loggedOut = { "GET /api/session": () => json({ detail: "unauthorized" }, 401) };

describe("session", () => {
  test("boots into the session the cookie proves", async () => {
    const { actor } = start(loggedIn);
    await waitFor(actor, (snapshot) => snapshot.matches("authenticated"));
    expect(actor.getSnapshot().context.agent).toBe("agent@demo.local");
  });

  test("boots into the login when there is no session", async () => {
    const { actor } = start(loggedOut);
    await waitFor(actor, (snapshot) => snapshot.matches("anonymous"));
    expect(actor.getSnapshot().context.agent).toBeNull();
  });

  test("a login posts the credentials as JSON, then asks who the session belongs to", async () => {
    let sessionOpen = false;
    const { actor, network } = start({
      "GET /api/session": () => (sessionOpen ? json({ agent_ref: "agent@demo.local" }) : json({ detail: "unauthorized" }, 401)),
      "POST /api/session": () => {
        sessionOpen = true;
        return noContent();
      },
    });
    await waitFor(actor, (snapshot) => snapshot.matches("anonymous"));

    actor.send({ type: "LOGIN", email: "agent@demo.local", password: "s3cret" });
    await waitFor(actor, (snapshot) => snapshot.matches("authenticated"));

    const [post] = network.to("POST /api/session");
    expect(post?.body).toEqual({ email: "agent@demo.local", password: "s3cret" });
    expect(post?.headers["Content-Type"]).toBe("application/json");
    expect(actor.getSnapshot().context.agent).toBe("agent@demo.local");
    expect(actor.getSnapshot().context.loginError).toBeNull();
  });

  test.each([
    ["wrong credentials", () => json({ detail: "invalid_credentials" }, 401), "invalid"],
    ["a malformed form", () => json({ detail: [{ loc: ["body", "email"], msg: "bad", type: "x" }] }, 422), "malformed"],
    ["a server that is down", () => json({ detail: "unavailable" }, 503), "unavailable"],
  ])("%s ends in the login with the reason", async (_label, answer, expected) => {
    const { actor } = start({ ...loggedOut, "POST /api/session": answer });
    await waitFor(actor, (snapshot) => snapshot.matches("anonymous"));
    actor.send({ type: "LOGIN", email: "a@b.c", password: "x" });
    await waitFor(actor, (snapshot) => snapshot.matches("signingIn"));
    await waitFor(actor, (snapshot) => snapshot.matches("anonymous"));
    expect(actor.getSnapshot().context.loginError).toBe(expected as "invalid");
    expect(actor.getSnapshot().context.agent).toBeNull();
  });

  test("a network failure on login is 'unavailable'", async () => {
    const network = fakeFetch(loggedOut);
    const api = createApi(async (input, init) => {
      if (init.method === "POST") throw new TypeError("network down");
      return network.fetch(input, init);
    });
    const actor = createActor(appMachine, { input: { api, storage: null, root: null } }).start();
    await waitFor(actor, (snapshot) => snapshot.matches("anonymous"));
    actor.send({ type: "LOGIN", email: "a@b.c", password: "x" });
    await waitFor(actor, (snapshot) => snapshot.matches("anonymous") && snapshot.context.loginError !== null);
    expect(actor.getSnapshot().context.loginError).toBe("unavailable");
  });

  test("logout goes back to the login, even if the server never heard it", async () => {
    const { actor } = start({ ...loggedIn, "DELETE /api/session": () => json({ detail: "unavailable" }, 503) });
    await waitFor(actor, (snapshot) => snapshot.matches("authenticated"));
    actor.send({ type: "LOGOUT" });
    await waitFor(actor, (snapshot) => snapshot.matches("anonymous"));
    expect(actor.getSnapshot().context.agent).toBeNull();
  });

  test("any 401 from the BFF ends the session and shows the login", async () => {
    const { actor } = start({ ...loggedIn, "GET /api/handoffs": () => json({ detail: "unauthorized" }, 401) });
    await waitFor(actor, (snapshot) => snapshot.matches("authenticated"));
    const api = actor.getSnapshot().context.api;
    await expect(api.listHandoffs()).rejects.toMatchObject({ status: 401 });
    await waitFor(actor, (snapshot) => snapshot.matches("anonymous"));
    expect(actor.getSnapshot().context.agent).toBeNull();
  });

  test("a wrong password is a 401 too, but it does not count as an expired session", async () => {
    const { actor } = start({ ...loggedOut, "POST /api/session": () => json({ detail: "invalid_credentials" }, 401) });
    await waitFor(actor, (snapshot) => snapshot.matches("anonymous"));
    actor.send({ type: "LOGIN", email: "a@b.c", password: "x" });
    await waitFor(actor, (snapshot) => snapshot.matches("anonymous") && snapshot.context.loginError === "invalid");
    expect(actor.getSnapshot().value).toBe("anonymous");
  });
});

describe("theme", () => {
  test("starts from the stored choice and applies it to <html>", () => {
    const storage = new FakeStorage();
    storage.setItem(THEME_STORAGE_KEY, "dark");
    const { actor, root } = start(loggedOut, { storage });
    expect(actor.getSnapshot().context.theme).toBe("dark");
    expect((root as FakeRoot).attributes.get("data-theme")).toBe("dark");
  });

  test.each([null, "", "blue", "DARK", "system", "{}"])("a stored value of %p is 'system' and leaves data-theme off", (stored) => {
    const storage = new FakeStorage();
    if (stored !== null) storage.setItem(THEME_STORAGE_KEY, stored);
    const { actor, root } = start(loggedOut, { storage });
    expect(actor.getSnapshot().context.theme).toBe("system");
    expect((root as FakeRoot).attributes.has("data-theme")).toBe(false);
  });

  test("choosing a theme sets data-theme and remembers it; 'system' clears both", () => {
    const storage = new FakeStorage();
    const { actor, root } = start(loggedOut, { storage });
    actor.send({ type: "THEME.SET", theme: "light" });
    expect((root as FakeRoot).attributes.get("data-theme")).toBe("light");
    expect(storage.getItem(THEME_STORAGE_KEY)).toBe("light");

    actor.send({ type: "THEME.SET", theme: "dark" });
    expect((root as FakeRoot).attributes.get("data-theme")).toBe("dark");
    expect(storage.getItem(THEME_STORAGE_KEY)).toBe("dark");

    actor.send({ type: "THEME.SET", theme: "system" });
    expect((root as FakeRoot).attributes.has("data-theme")).toBe(false);
    expect(storage.getItem(THEME_STORAGE_KEY)).toBeNull();
  });

  test("storage that throws never breaks the theme, on read or on write", () => {
    expect(readStoredTheme(throwingStorage)).toBe("system");
    const { actor, root } = start(loggedOut, { storage: throwingStorage });
    actor.send({ type: "THEME.SET", theme: "dark" });
    expect(actor.getSnapshot().context.theme).toBe("dark");
    expect((root as FakeRoot).attributes.get("data-theme")).toBe("dark");
  });

  test("no storage at all is fine", () => {
    const { actor } = start(loggedOut, { storage: null });
    actor.send({ type: "THEME.SET", theme: "light" });
    expect(actor.getSnapshot().context.theme).toBe("light");
  });

  test("the theme survives a login and a logout", async () => {
    const { actor } = start({ ...loggedIn, "DELETE /api/session": () => noContent() });
    actor.send({ type: "THEME.SET", theme: "dark" });
    await waitFor(actor, (snapshot) => snapshot.matches("authenticated"));
    actor.send({ type: "LOGOUT" });
    await waitFor(actor, (snapshot) => snapshot.matches("anonymous"));
    expect(actor.getSnapshot().context.theme).toBe("dark");
  });
});

describe("language", () => {
  test("starts in Spanish and sets <html lang>", () => {
    const { actor, root } = start(loggedOut);
    expect(actor.getSnapshot().context.lang).toBe("es");
    expect((root as FakeRoot).attributes.get("lang")).toBe("es");
  });

  test("changes to Portuguese and English", () => {
    const { actor, root } = start(loggedOut);
    actor.send({ type: "LANG.SET", lang: "pt" });
    expect(actor.getSnapshot().context.lang).toBe("pt");
    expect((root as FakeRoot).attributes.get("lang")).toBe("pt");
    actor.send({ type: "LANG.SET", lang: "en" });
    expect((root as FakeRoot).attributes.get("lang")).toBe("en");
  });
});
