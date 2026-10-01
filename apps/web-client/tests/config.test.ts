import { describe, expect, test } from "bun:test";
import { DEFAULT_ORCHESTRATOR_URL, DEFAULT_PORT, loadConfig } from "../src/config";

describe("loadConfig", () => {
  test("defaults", () => {
    expect(loadConfig({})).toEqual({ port: DEFAULT_PORT, orchestratorUrl: DEFAULT_ORCHESTRATOR_URL });
    expect(DEFAULT_PORT).toBe(5173);
    expect(DEFAULT_ORCHESTRATOR_URL).toBe("http://localhost:8080");
  });

  test("reads PORT and ORCHESTRATOR_URL and drops a trailing slash", () => {
    expect(loadConfig({ PORT: "4000", ORCHESTRATOR_URL: "http://orchestrator:8080/" })).toEqual({
      port: 4000,
      orchestratorUrl: "http://orchestrator:8080",
    });
  });

  test("an empty value means the default", () => {
    expect(loadConfig({ PORT: "", ORCHESTRATOR_URL: " " })).toEqual({
      port: DEFAULT_PORT,
      orchestratorUrl: DEFAULT_ORCHESTRATOR_URL,
    });
  });

  test("a bad value fails with the variable's name", () => {
    expect(() => loadConfig({ PORT: "abc" })).toThrow("PORT");
    expect(() => loadConfig({ PORT: "70000" })).toThrow("PORT");
    expect(() => loadConfig({ ORCHESTRATOR_URL: "orchestrator:8080" })).toThrow("ORCHESTRATOR_URL");
    expect(() => loadConfig({ ORCHESTRATOR_URL: "ftp://orchestrator" })).toThrow("ORCHESTRATOR_URL");
  });
});
