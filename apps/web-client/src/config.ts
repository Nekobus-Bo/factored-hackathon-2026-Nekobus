// Runtime configuration of the server. Two settings, both from the environment.
//
//   PORT              port to listen on (default 5173)
//   ORCHESTRATOR_URL  where the four chat routes are forwarded (default http://localhost:8080)

export const DEFAULT_PORT = 5173;
export const DEFAULT_ORCHESTRATOR_URL = "http://localhost:8080";

export interface Config {
  port: number;
  /** Origin (and optional path prefix) of the orchestrator, without a trailing slash. */
  orchestratorUrl: string;
}

/** Fails with a message that names the variable, so a bad compose file is found at startup. */
export function loadConfig(env: Record<string, string | undefined> = process.env): Config {
  const rawPort = env.PORT?.trim();
  let port = DEFAULT_PORT;
  if (rawPort) {
    port = Number(rawPort);
    if (!Number.isInteger(port) || port < 0 || port > 65535) {
      throw new Error(`PORT must be an integer from 0 to 65535, got "${rawPort}"`);
    }
  }

  const rawUrl = env.ORCHESTRATOR_URL?.trim() || DEFAULT_ORCHESTRATOR_URL;
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    throw new Error(`ORCHESTRATOR_URL must be an absolute http(s) URL, got "${rawUrl}"`);
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error(`ORCHESTRATOR_URL must be an http(s) URL, got "${rawUrl}"`);
  }
  return { port, orchestratorUrl: url.toString().replace(/\/+$/, "") };
}
