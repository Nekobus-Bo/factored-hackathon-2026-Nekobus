// The browser's side of the BFF: one function per route of `backofficeBffRoutes`.
//
// URLs come from the contract's route table, every answer is validated with the route's response schema,
// and every failure is an `ApiError` (never a bare `Response`), so a machine's `onError` sees one shape.
// The browser never talks to the orchestrator or banking-core: same origin, `/api` only.

import {
  ApiErrorSchema,
  backofficeBffRoutes as routes,
  routePath,
  toQueryString,
  type AgentMessageRequest,
  type CloseCaseRequest,
  type EscalateCaseRequest,
  type HandoffStatus,
  type PolicyConfigRequest,
  type RouteShape,
  type ToolPolicyRequest,
  type ValidationIssue,
} from "@pattern-blue/contracts";
import type { z } from "zod";

export type ApiErrorKind =
  /** The server answered with an error status. */
  | "http"
  /** No answer: offline, the server is down, the request was aborted. */
  | "network"
  /** A success whose body does not match the contract. */
  | "invalid";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  /** HTTP status; 0 when there was no answer. */
  readonly status: number;
  /** The `detail` of the BFF's error body: a code, or the list of validation issues of a 422. */
  readonly detail: string | ValidationIssue[] | null;
  /** Seconds from `Retry-After`, when the server sent one. */
  readonly retryAfterSeconds: number | null;

  constructor(init: { kind: ApiErrorKind; status: number; detail?: string | ValidationIssue[] | null; retryAfterSeconds?: number | null }) {
    super(`${init.kind} ${init.status}${typeof init.detail === "string" ? ` ${init.detail}` : ""}`);
    this.name = "ApiError";
    this.kind = init.kind;
    this.status = init.status;
    this.detail = init.detail ?? null;
    this.retryAfterSeconds = init.retryAfterSeconds ?? null;
  }
}

export const isApiError = (error: unknown): error is ApiError => error instanceof ApiError;

type Output<R extends RouteShape> = R extends { response: infer S extends z.ZodType } ? z.output<S> : void;

export interface ApiOptions {
  /** Called on any 401 except the login's own: the session ended, whatever asked. */
  onUnauthorized?: () => void;
}

type FetchLike = (input: string, init: RequestInit) => Promise<Response>;

const fillPath = routePath as (route: RouteShape, params?: Record<string, string>) => string;

export function createApi(fetchImpl: FetchLike = (input, init) => globalThis.fetch(input, init), options: ApiOptions = {}) {
  async function request<R extends RouteShape>(
    route: R,
    input: { params?: Record<string, string>; query?: Record<string, string | number | undefined | readonly string[]>; body?: unknown } = {},
  ): Promise<Output<R>> {
    const url = fillPath(route, input.params) + (input.query ? toQueryString(input.query) : "");
    const headers: Record<string, string> = { Accept: "application/json" };
    // The BFF wants the JSON content type on every mutating route, with or without a body.
    if (route.method !== "GET") headers["Content-Type"] = "application/json";

    let response: Response;
    try {
      response = await fetchImpl(url, {
        method: route.method,
        headers,
        credentials: "same-origin",
        body: input.body === undefined ? undefined : JSON.stringify(input.body),
      });
    } catch {
      throw new ApiError({ kind: "network", status: 0 });
    }

    if (response.ok) {
      if (!route.response) return undefined as Output<R>;
      const parsed = route.response.safeParse(await response.json().catch(() => undefined));
      if (!parsed.success) throw new ApiError({ kind: "invalid", status: response.status });
      return parsed.data as Output<R>;
    }

    const error = ApiErrorSchema.safeParse(await response.json().catch(() => undefined));
    const retryAfter = Number(response.headers.get("retry-after"));
    if (response.status === 401 && (route as RouteShape) !== routes.login) options.onUnauthorized?.();
    throw new ApiError({
      kind: "http",
      status: response.status,
      detail: error.success ? error.data.detail : null,
      retryAfterSeconds: Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null,
    });
  }

  return {
    getSession: () => request(routes.getSession),
    login: (email: string, password: string) => request(routes.login, { body: { email, password } }),
    logout: () => request(routes.logout),

    listHandoffs: (statuses?: readonly HandoffStatus[]) => request(routes.listHandoffs, { query: { status: statuses } }),
    getHandoff: (ref: string) => request(routes.getHandoff, { params: { ref } }),
    claimHandoff: (ref: string) => request(routes.claimHandoff, { params: { ref } }),
    closeHandoff: (ref: string, body: CloseCaseRequest) => request(routes.closeHandoff, { params: { ref }, body }),
    escalateHandoff: (ref: string, body: EscalateCaseRequest) => request(routes.escalateHandoff, { params: { ref }, body }),

    getConversation: (id: string) => request(routes.getConversation, { params: { id } }),
    sendAgentMessage: (id: string, message: AgentMessageRequest) => request(routes.sendAgentMessage, { params: { id }, body: message }),

    getPolicyConfig: () => request(routes.getPolicyConfig),
    putPolicyConfig: (body: PolicyConfigRequest) => request(routes.putPolicyConfig, { body }),
    getToolPolicy: () => request(routes.getToolPolicy),
    putToolPolicy: (body: ToolPolicyRequest) => request(routes.putToolPolicy, { body }),
    resetDemo: () => request(routes.resetDemo),

    getMetrics: (hours: number) => request(routes.getMetrics, { query: { hours } }),

    getDetective: () => request(routes.getDetective),
    setDetective: (enabled: boolean) => request(routes.setDetective, { body: { enabled } }),
  };
}

export type Api = ReturnType<typeof createApi>;
