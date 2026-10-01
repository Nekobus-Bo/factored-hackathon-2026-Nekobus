// The back-office BFF: exactly the routes of `backofficeBffRoutes`, nothing else under `/api`.
//
// Every request goes through the same gate, in this order:
//   1. the route must exist (method and path), otherwise 404;
//   2. every route but `POST /api/session` needs the signed session cookie, otherwise 401;
//   3. a mutating route (anything but GET) needs `Content-Type: application/json`, otherwise 415;
//   4. params, query and body are validated with the contract's schemas, otherwise 422 (400 for bad JSON).
// Then the handler calls the upstream with the server-held token and answers with the validated result.
// The browser's headers never reach an upstream: `X-Agent-Ref` is built from the session, and only from it.

import {
  AGENT_REF_HEADER,
  BackofficeHandoffDetailSchema,
  ERROR_DETAIL,
  backofficeBffRoutes,
  bankingAdminRoutes,
  orchestratorAgentRoutes,
  queryFromSearchParams,
  type RouteShape,
  type ValidationIssue,
} from "@pattern-blue/contracts";
import type { z } from "zod";
import type { Config } from "./config";
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
  type SessionPayload,
} from "./session";
import { Upstream, type Logger, type Outcome } from "./upstream";

type BffRoutes = typeof backofficeBffRoutes;
type RouteName = keyof BffRoutes;
type AuthedRouteName = Exclude<RouteName, "login">;

type Parsed<S> = S extends z.ZodType ? z.output<S> : undefined;
interface Ctx<N extends RouteName> {
  req: Request;
  session: SessionPayload;
  params: BffRoutes[N] extends { params: infer P } ? Parsed<P> : undefined;
  query: BffRoutes[N] extends { query: infer Q } ? Parsed<Q> : undefined;
  body: BffRoutes[N] extends { body: infer B } ? Parsed<B> : undefined;
}
type Handler<N extends RouteName> = (ctx: Ctx<N>) => Promise<Response>;

/** The orchestrator's answer when a customer turn holds the conversation lock for more than 10 s. */
const TURN_IN_PROGRESS = "turn_in_progress";

const BASE_HEADERS = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" } as const;

function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return Response.json(body, { status, headers: { ...BASE_HEADERS, ...headers } });
}

function empty(status: number, headers: Record<string, string> = {}): Response {
  return new Response(null, { status, headers: { ...BASE_HEADERS, ...headers } });
}

const errorBody = (detail: string) => ({ detail });

function issues(prefix: string, error: z.ZodError): ValidationIssue[] {
  return error.issues.map((issue) => ({ loc: [prefix, ...issue.path.map((key) => (typeof key === "symbol" ? String(key) : key))], msg: issue.message, type: issue.code }));
}

/** What an upstream failure means for the browser. */
function failure(outcome: Exclude<Outcome<unknown>, { kind: "ok" }>, log: Logger): Response {
  switch (outcome.kind) {
    case "unreachable":
      return json(503, errorBody(ERROR_DETAIL.unavailable));
    case "invalid":
      return json(502, errorBody("invalid_upstream_response"));
    case "http": {
      const { status, detail } = outcome;
      // Our own token was refused: a deployment mistake, not something the agent can fix by logging in again.
      if (status === 401) {
        log("an upstream refused the BFF's token");
        return json(502, errorBody("upstream_unauthorized"));
      }
      if (status === 503 && detail === TURN_IN_PROGRESS) {
        return json(503, errorBody(TURN_IN_PROGRESS), { "Retry-After": outcome.retryAfter ?? "2" });
      }
      if (status === 503) return json(503, errorBody(ERROR_DETAIL.unavailable));
      if (status >= 500) return json(502, errorBody("upstream_error"));
      return json(status, { detail: detail ?? "upstream_error" }, status === 429 && outcome.retryAfter ? { "Retry-After": outcome.retryAfter } : {});
    }
  }
}

export interface BffDeps {
  fetch?: (input: string, init: RequestInit) => Promise<Response>;
  now?: () => number;
  log?: Logger;
  compare?: Compare;
}

export interface Bff {
  handle(req: Request): Promise<Response>;
}

interface CompiledRoute {
  name: RouteName;
  route: RouteShape;
  segments: string[];
}

function compile(): CompiledRoute[] {
  return (Object.entries(backofficeBffRoutes) as [RouteName, RouteShape][]).map(([name, route]) => ({
    name,
    route,
    segments: route.pattern.split("/"),
  }));
}

/** Path parameters when `segments` (a pattern) matches `pathname`, otherwise null. */
function matchPath(segments: string[], pathname: string): Record<string, string> | null {
  const actual = pathname.split("/");
  if (actual.length !== segments.length) return null;
  const params: Record<string, string> = {};
  for (const [index, segment] of segments.entries()) {
    const value = actual[index] as string;
    if (segment.startsWith(":")) {
      if (value === "") return null;
      try {
        params[segment.slice(1)] = decodeURIComponent(value);
      } catch {
        return null;
      }
    } else if (segment !== value) {
      return null;
    }
  }
  return params;
}

function isJson(req: Request): boolean {
  const type = req.headers.get("content-type");
  return type !== null && type.split(";")[0]?.trim().toLowerCase() === "application/json";
}

export function createBff(config: Config, deps: BffDeps = {}): Bff {
  const log: Logger = deps.log ?? ((message) => console.error(message));
  const now = deps.now ?? Date.now;
  const compare = deps.compare ?? safeEqual;
  const upstream = new Upstream(config, deps.fetch, log);
  const routes = compile();

  const admin = bankingAdminRoutes;
  const agent = orchestratorAgentRoutes;

  const fail = (outcome: Exclude<Outcome<unknown>, { kind: "ok" }>) => failure(outcome, log);
  const ok = <N extends RouteName>(name: N, data: unknown) => json(backofficeBffRoutes[name].successStatus, data);

  // --- Session ---------------------------------------------------------------------------------------

  const login = async (body: z.output<typeof backofficeBffRoutes.login.body>): Promise<Response> => {
    const matches = credentialsMatch(body, { email: config.agentEmail, password: config.agentPassword }, compare);
    if (!matches) return json(401, errorBody("invalid_credentials"));
    const exp = Math.floor(now() / 1000) + config.sessionTtlSeconds;
    // The agent is whoever the server configured, spelled the configured way, not whatever was typed.
    const value = signSession({ agent_ref: config.agentEmail, exp }, config.sessionSecret);
    return empty(204, { "Set-Cookie": sessionSetCookie(value, { secure: config.production, maxAgeSeconds: config.sessionTtlSeconds }) });
  };

  // --- Handlers of the authenticated routes -----------------------------------------------------------

  const handlers: { [N in AuthedRouteName]: Handler<N> } = {
    logout: async () => empty(204, { "Set-Cookie": sessionClearCookie({ secure: config.production }) }),

    getSession: async ({ session }) => ok("getSession", { agent_ref: session.agent_ref }),

    listHandoffs: async ({ query }) => {
      const outcome = await upstream.call("banking-core", admin.listHandoffs, { query: { status: query.status } });
      return outcome.kind === "ok" ? ok("listHandoffs", outcome.data) : fail(outcome);
    },

    getHandoff: async ({ params }) => {
      const detail = await upstream.call("banking-core", admin.getHandoff, { params: { handoff_ref: params.ref } });
      if (detail.kind !== "ok") return fail(detail);
      const conversation = await upstream.call("orchestrator", agent.conversationForSession, {
        params: { session_ref: detail.data.session_ref },
      });
      // 404 is the contract's "no conversation": its TTL expired, or the agent API does not know the session.
      if (conversation.kind !== "ok" && !(conversation.kind === "http" && conversation.status === 404)) return fail(conversation);
      const conversation_id = conversation.kind === "ok" ? conversation.data.conversation_id : null;
      return ok("getHandoff", BackofficeHandoffDetailSchema.parse({ ...detail.data, conversation_id }));
    },

    claimHandoff: async ({ params, session }) => {
      // Step 1, in banking-core: the claim is what is audited as the agent's takeover (ADR-0004).
      const claim = await upstream.call("banking-core", admin.claimHandoff, {
        params: { handoff_ref: params.ref },
        body: { agent_ref: session.agent_ref },
      });
      if (claim.kind !== "ok") return fail(claim);

      // Step 2, in the orchestrator. The claim is done and idempotent for this agent, so a failure here is
      // reported as such and the same call can simply be repeated.
      const claimedButFailed = () => json(502, errorBody(ERROR_DETAIL.claimedButTakeoverFailed));
      const conversation = await upstream.call("orchestrator", agent.conversationForSession, {
        params: { session_ref: claim.data.session_ref },
      });
      if (conversation.kind !== "ok") return claimedButFailed();

      const takeover = await upstream.call("orchestrator", agent.takeover, {
        params: { id: conversation.data.conversation_id },
        body: { agent_ref: session.agent_ref, handoff_ref: claim.data.handoff_ref },
      });
      // Another agent holds the conversation: that is an answer, not a failure of the step.
      if (takeover.kind === "http" && takeover.status === 409) return fail(takeover);
      if (takeover.kind !== "ok") return claimedButFailed();

      return ok("claimHandoff", { handoff: claim.data, takeover: takeover.data });
    },

    getConversation: async ({ params }) => {
      const outcome = await upstream.call("orchestrator", agent.getConversation, { params: { id: params.id } });
      return outcome.kind === "ok" ? ok("getConversation", outcome.data) : fail(outcome);
    },

    sendAgentMessage: async ({ params, body, session }) => {
      const outcome = await upstream.call("orchestrator", agent.sendMessage, {
        params: { id: params.id },
        body,
        headers: { [AGENT_REF_HEADER]: session.agent_ref },
      });
      return outcome.kind === "ok" ? ok("sendAgentMessage", outcome.data) : fail(outcome);
    },

    getPolicyConfig: async () => {
      const outcome = await upstream.call("banking-core", admin.getPolicyConfig);
      return outcome.kind === "ok" ? ok("getPolicyConfig", outcome.data) : fail(outcome);
    },

    putPolicyConfig: async ({ body }) => {
      const outcome = await upstream.call("banking-core", admin.putPolicyConfig, { body });
      return outcome.kind === "ok" ? ok("putPolicyConfig", outcome.data) : fail(outcome);
    },

    getToolPolicy: async () => {
      const outcome = await upstream.call("banking-core", admin.getToolPolicy);
      return outcome.kind === "ok" ? ok("getToolPolicy", outcome.data) : fail(outcome);
    },

    putToolPolicy: async ({ body }) => {
      const outcome = await upstream.call("banking-core", admin.putToolPolicy, { body });
      return outcome.kind === "ok" ? ok("putToolPolicy", outcome.data) : fail(outcome);
    },

    resetDemo: async () => {
      const outcome = await upstream.call("banking-core", admin.resetDemoFixtures);
      return outcome.kind === "ok" ? ok("resetDemo", outcome.data) : fail(outcome);
    },

    getMetrics: async ({ query }) => {
      const outcome = await upstream.call("banking-core", admin.getMetrics, { query: { hours: query.hours } });
      return outcome.kind === "ok" ? ok("getMetrics", outcome.data) : fail(outcome);
    },
  };

  // --- Dispatch --------------------------------------------------------------------------------------

  async function handle(req: Request): Promise<Response> {
    const url = new URL(req.url);
    const notFound = () => json(404, errorBody("not_found"));

    let matched: { compiled: CompiledRoute; params: Record<string, string> } | null = null;
    for (const compiled of routes) {
      if (compiled.route.method !== req.method) continue;
      const params = matchPath(compiled.segments, url.pathname);
      if (params) {
        matched = { compiled, params };
        break;
      }
    }
    if (!matched) return notFound();
    const { name, route } = matched.compiled;

    let session: SessionPayload | null = null;
    if (name !== "login") {
      session = readSession(cookieValue(req.headers.get("cookie"), SESSION_COOKIE), config.sessionSecret, now());
      if (!session) return json(401, errorBody("unauthorized"));
    }

    if (req.method !== "GET" && !isJson(req)) return json(415, errorBody("unsupported_media_type"));

    let params: unknown;
    if (route.params) {
      const parsed = route.params.safeParse(matched.params);
      if (!parsed.success) return json(422, { detail: issues("path", parsed.error) });
      params = parsed.data;
    }

    let query: unknown;
    if (route.query) {
      const parsed = route.query.safeParse(queryFromSearchParams(url.searchParams));
      if (!parsed.success) return json(422, { detail: issues("query", parsed.error) });
      query = parsed.data;
    }

    let body: unknown;
    if (route.body) {
      const text = await req.text();
      let raw: unknown = undefined;
      if (text !== "") {
        try {
          raw = JSON.parse(text);
        } catch {
          return json(400, errorBody("invalid_json"));
        }
      } else if (route.bodyOptional) {
        raw = {};
      }
      const parsed = route.body.safeParse(raw);
      if (!parsed.success) return json(422, { detail: issues("body", parsed.error) });
      body = parsed.data;
    }

    if (name === "login") return login(body as z.output<typeof backofficeBffRoutes.login.body>);
    const handler = handlers[name as AuthedRouteName] as (ctx: unknown) => Promise<Response>;
    return handler({ req, session, params, query, body });
  }

  return { handle };
}
