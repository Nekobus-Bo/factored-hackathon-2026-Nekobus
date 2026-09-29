// Calls to the two services behind the BFF, each with its own server-held token.
//
//   banking-core  /v1/admin/*   Authorization: Bearer <ADMIN_API_TOKEN>
//   orchestrator  /v1/agent/*   Authorization: Bearer <AGENT_API_TOKEN>
//
// A call is described by a route of the contract (`bankingAdminRoutes`, `orchestratorAgentRoutes`): the
// path is filled from the route's pattern, and the answer is validated with the route's response schema,
// so the BFF never forwards a shape it did not check. The outcome is data, not an exception: the route
// handlers decide what each failure means for the browser.

import { ApiErrorSchema, routePath, toQueryString, type RouteShape, type ValidationIssue } from "@pattern-blue/contracts";
import type { z } from "zod";
import type { Config } from "./config";

export type Service = "banking-core" | "orchestrator";

export type ResponseOf<R extends RouteShape> = R extends { response: infer S extends z.ZodType } ? z.output<S> : undefined;

export type Outcome<T> =
  | { kind: "ok"; data: T }
  /** Connection refused, DNS failure, timeout, or a redirect (an upstream never redirects). */
  | { kind: "unreachable" }
  /** A 2xx whose body or status does not match the contract. */
  | { kind: "invalid"; problem: string }
  /** The upstream answered with an error status. `detail` is FastAPI's, when it sent one. */
  | { kind: "http"; status: number; detail: string | ValidationIssue[] | null; retryAfter: string | null };

export interface CallOptions {
  params?: Record<string, string>;
  query?: Record<string, string | number | boolean | undefined | readonly string[]>;
  body?: unknown;
  /** Extra request headers. The browser's own headers are never forwarded, only what a handler names here. */
  headers?: Record<string, string>;
}

export type Logger = (message: string) => void;

type Fetch = (input: string, init: RequestInit) => Promise<Response>;

const fillPath = routePath as (route: RouteShape, params?: Record<string, string>) => string;

export class Upstream {
  constructor(
    private readonly config: Pick<Config, "orchestratorUrl" | "bankingCoreUrl" | "adminApiToken" | "agentApiToken" | "upstreamTimeoutMs">,
    private readonly fetchImpl: Fetch = (input, init) => fetch(input, init),
    private readonly log: Logger = (message) => console.error(message),
  ) {}

  private target(service: Service): { base: string; token: string } {
    return service === "banking-core"
      ? { base: this.config.bankingCoreUrl, token: this.config.adminApiToken }
      : { base: this.config.orchestratorUrl, token: this.config.agentApiToken };
  }

  async call<R extends RouteShape>(service: Service, route: R, options: CallOptions = {}): Promise<Outcome<ResponseOf<R>>> {
    const { base, token } = this.target(service);
    const url = `${base}${fillPath(route, options.params)}${options.query ? toQueryString(options.query) : ""}`;
    const label = `${service} ${route.method} ${route.pattern}`;

    const headers: Record<string, string> = { Accept: "application/json", ...options.headers, Authorization: `Bearer ${token}` };
    if (options.body !== undefined) headers["Content-Type"] = "application/json";

    let status: number;
    let retryAfter: string | null;
    let text: string;
    try {
      const response = await this.fetchImpl(url, {
        method: route.method,
        headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        signal: AbortSignal.timeout(this.config.upstreamTimeoutMs),
        redirect: "error",
      });
      status = response.status;
      retryAfter = response.headers.get("retry-after");
      text = await response.text();
    } catch (error) {
      this.log(`${label}: unreachable (${error instanceof Error ? error.message : String(error)})`);
      return { kind: "unreachable" };
    }

    let json: unknown = undefined;
    let jsonError = false;
    if (text !== "") {
      try {
        json = JSON.parse(text);
      } catch {
        jsonError = true;
      }
    }

    if (status >= 200 && status < 300) {
      if (status !== route.successStatus) {
        this.log(`${label}: answered ${status}, the contract says ${route.successStatus}`);
        return { kind: "invalid", problem: `status ${status}, expected ${route.successStatus}` };
      }
      if (!route.response) return { kind: "ok", data: undefined as ResponseOf<R> };
      if (jsonError) {
        this.log(`${label}: the body is not JSON`);
        return { kind: "invalid", problem: "body is not JSON" };
      }
      const parsed = route.response.safeParse(json);
      if (!parsed.success) {
        const problem = parsed.error.issues.map((issue) => `${issue.path.join(".") || "(body)"}: ${issue.message}`).join("; ");
        this.log(`${label}: the answer does not match the contract (${problem})`);
        return { kind: "invalid", problem };
      }
      return { kind: "ok", data: parsed.data as ResponseOf<R> };
    }

    const error = ApiErrorSchema.safeParse(json);
    return { kind: "http", status, detail: error.success ? error.data.detail : null, retryAfter };
  }
}
