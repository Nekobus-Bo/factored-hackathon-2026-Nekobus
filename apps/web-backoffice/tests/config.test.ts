import { describe, expect, test } from "bun:test";
import { ConfigError, DEVELOPMENT_DEFAULTS, loadConfig } from "../src/bff/config";

const production = {
  APP_ENV: "production",
  ADMIN_API_TOKEN: "a-real-admin-secret",
  AGENT_API_TOKEN: "a-real-agent-secret",
  DEMO_AGENT_PASSWORD: "a-real-password",
  BACKOFFICE_SESSION_SECRET: "a-random-session-secret-of-some-length",
};

function problemsOf(env: Record<string, string | undefined>): readonly string[] {
  try {
    loadConfig(env);
  } catch (error) {
    if (error instanceof ConfigError) return error.problems;
    throw error;
  }
  return [];
}

describe("configuration", () => {
  test("the defaults are the ones of .env.example", () => {
    const config = loadConfig({});
    expect(config).toMatchObject({
      port: 5174,
      appEnv: "development",
      production: false,
      orchestratorUrl: "http://localhost:8080",
      bankingCoreUrl: "http://localhost:8081",
      adminApiToken: "dev-only-admin-token",
      agentApiToken: "dev-only-agent-token",
      agentEmail: "agent@demo.local",
      agentPassword: "demo-only-change-me",
      sessionTtlSeconds: 8 * 60 * 60,
    });
    expect(config.sessionSecret).toBe(DEVELOPMENT_DEFAULTS.sessionSecret);
  });

  test("reads the environment and drops trailing slashes from the URLs", () => {
    const config = loadConfig({
      PORT: "6000",
      ORCHESTRATOR_URL: "http://orchestrator:8080/",
      BANKING_CORE_URL: "http://banking-core:8081//",
      DEMO_AGENT_EMAIL: "ana@example.com",
    });
    expect(config.port).toBe(6000);
    expect(config.orchestratorUrl).toBe("http://orchestrator:8080");
    expect(config.bankingCoreUrl).toBe("http://banking-core:8081");
    expect(config.agentEmail).toBe("ana@example.com");
  });

  test("a blank variable is the same as an unset one", () => {
    expect(loadConfig({ PORT: "", ADMIN_API_TOKEN: "  " })).toMatchObject({ port: 5174, adminApiToken: "dev-only-admin-token" });
  });

  test("reports every bad value at once", () => {
    const problems = problemsOf({ PORT: "abc", ORCHESTRATOR_URL: "not a url", DEMO_AGENT_EMAIL: "no at sign" });
    expect(problems).toHaveLength(3);
    expect(problems.join("\n")).toContain("PORT");
    expect(problems.join("\n")).toContain("ORCHESTRATOR_URL");
    expect(problems.join("\n")).toContain("DEMO_AGENT_EMAIL");
  });

  describe("under APP_ENV=production", () => {
    test("starts with real secrets", () => {
      expect(loadConfig(production)).toMatchObject({ production: true, appEnv: "production" });
    });

    test("APP_ENV is not case sensitive", () => {
      expect(problemsOf({ ...production, APP_ENV: "Production", DEMO_AGENT_PASSWORD: undefined })).toHaveLength(1);
    });

    test.each([
      ["DEMO_AGENT_PASSWORD", "demo-only-change-me"],
      ["BACKOFFICE_SESSION_SECRET", "dev-only-backoffice-session-secret"],
      ["ADMIN_API_TOKEN", "dev-only-admin-token"],
      ["AGENT_API_TOKEN", "dev-only-agent-token"],
    ])("refuses the public development value of %s", (name, value) => {
      const problems = problemsOf({ ...production, [name]: value });
      expect(problems).toHaveLength(1);
      expect(problems[0]).toContain(name);
    });

    test.each(["DEMO_AGENT_PASSWORD", "BACKOFFICE_SESSION_SECRET", "ADMIN_API_TOKEN", "AGENT_API_TOKEN"])(
      "refuses %s when it is unset or empty",
      (name) => {
        expect(problemsOf({ ...production, [name]: undefined })).toHaveLength(1);
        expect(problemsOf({ ...production, [name]: "" })).toHaveLength(1);
      },
    );

    test("names every development value it finds", () => {
      const problems = problemsOf({ APP_ENV: "production" });
      expect(problems).toHaveLength(4);
    });

    test("the same defaults are accepted outside production", () => {
      expect(problemsOf({ APP_ENV: "development" })).toEqual([]);
      expect(problemsOf({ APP_ENV: "staging" })).toEqual([]);
    });
  });
});
