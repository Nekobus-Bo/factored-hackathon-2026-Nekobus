// Configuration of the back-office server, read once from the environment.
//
// Everything here is a seed for a running service, not a constant of the design: the ports, the two
// upstream URLs, the two server-held tokens and the demo agent's login. The development values are
// public (they are in .env.example and in the repository), so under APP_ENV=production the server
// refuses to start with any of them.

import { AgentRefSchema } from "@pattern-blue/contracts";

/** The public development values. Each one is refused when APP_ENV=production. */
export const DEVELOPMENT_DEFAULTS = {
  adminToken: "dev-only-admin-token",
  agentToken: "dev-only-agent-token",
  agentEmail: "agent@demo.local",
  agentPassword: "demo-only-change-me",
  sessionSecret: "dev-only-backoffice-session-secret",
} as const;

/** Session lifetime: 8 hours (docs/front-ends.md, decision 4). */
export const SESSION_TTL_SECONDS = 8 * 60 * 60;

export interface Config {
  port: number;
  appEnv: string;
  production: boolean;
  /** Orchestrator base URL, no trailing slash. Reached with the agent API token. */
  orchestratorUrl: string;
  /** banking-core base URL, no trailing slash. Reached with the admin API token. */
  bankingCoreUrl: string;
  adminApiToken: string;
  agentApiToken: string;
  agentEmail: string;
  agentPassword: string;
  sessionSecret: string;
  sessionTtlSeconds: number;
  /** How long the BFF waits for an upstream before it answers 503 `unavailable`. */
  upstreamTimeoutMs: number;
}

/** Everything that is wrong with the environment, so an operator fixes it in one pass. */
export class ConfigError extends Error {
  readonly problems: readonly string[];

  constructor(problems: readonly string[]) {
    super(`invalid configuration:\n${problems.map((problem) => `  - ${problem}`).join("\n")}`);
    this.name = "ConfigError";
    this.problems = problems;
  }
}

export type Env = Record<string, string | undefined>;

/** An unset or blank variable falls back to `fallback`; the production check then refuses a development one. */
function read(env: Env, name: string, fallback: string): string {
  const value = env[name]?.trim();
  return value === undefined || value === "" ? fallback : value;
}

function readUrl(env: Env, name: string, fallback: string, problems: string[]): string {
  const value = read(env, name, fallback);
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") throw new Error("not http(s)");
    return value.replace(/\/+$/, "");
  } catch {
    problems.push(`${name} must be an http(s) URL, got ${JSON.stringify(value)}`);
    return fallback;
  }
}

function readInt(env: Env, name: string, fallback: number, min: number, max: number, problems: string[]): number {
  const raw = env[name]?.trim();
  if (raw === undefined || raw === "") return fallback;
  const value = Number(raw);
  if (!Number.isInteger(value) || value < min || value > max) {
    problems.push(`${name} must be an integer from ${min} to ${max}, got ${JSON.stringify(raw)}`);
    return fallback;
  }
  return value;
}

export function loadConfig(env: Env = process.env): Config {
  const problems: string[] = [];

  const appEnv = read(env, "APP_ENV", "development");
  const production = appEnv.toLowerCase() === "production";

  const config: Config = {
    port: readInt(env, "PORT", 5174, 1, 65535, problems),
    appEnv,
    production,
    orchestratorUrl: readUrl(env, "ORCHESTRATOR_URL", "http://localhost:8080", problems),
    bankingCoreUrl: readUrl(env, "BANKING_CORE_URL", "http://localhost:8081", problems),
    adminApiToken: read(env, "ADMIN_API_TOKEN", DEVELOPMENT_DEFAULTS.adminToken),
    agentApiToken: read(env, "AGENT_API_TOKEN", DEVELOPMENT_DEFAULTS.agentToken),
    agentEmail: read(env, "DEMO_AGENT_EMAIL", DEVELOPMENT_DEFAULTS.agentEmail),
    agentPassword: read(env, "DEMO_AGENT_PASSWORD", DEVELOPMENT_DEFAULTS.agentPassword),
    sessionSecret: read(env, "BACKOFFICE_SESSION_SECRET", DEVELOPMENT_DEFAULTS.sessionSecret),
    sessionTtlSeconds: SESSION_TTL_SECONDS,
    upstreamTimeoutMs: readInt(env, "UPSTREAM_TIMEOUT_MS", 10_000, 100, 120_000, problems),
  };

  // The agent's e-mail travels in the session cookie, in `X-Agent-Ref` and in an audit row.
  if (!AgentRefSchema.safeParse(config.agentEmail).success) {
    problems.push("DEMO_AGENT_EMAIL must look like an e-mail address (something@something, no spaces)");
  }

  if (production) {
    if (config.adminApiToken === DEVELOPMENT_DEFAULTS.adminToken) {
      problems.push("ADMIN_API_TOKEN is unset or the public development token; set a secret of your own");
    }
    if (config.agentApiToken === DEVELOPMENT_DEFAULTS.agentToken) {
      problems.push("AGENT_API_TOKEN is unset or the public development token; set a secret of your own");
    }
    if (config.agentPassword === DEVELOPMENT_DEFAULTS.agentPassword) {
      problems.push("DEMO_AGENT_PASSWORD is unset or the public default; set a password of your own");
    }
    if (config.sessionSecret === DEVELOPMENT_DEFAULTS.sessionSecret) {
      problems.push("BACKOFFICE_SESSION_SECRET is unset or the public development default; set a random secret");
    }
  }

  if (problems.length > 0) throw new ConfigError(problems);
  return config;
}
