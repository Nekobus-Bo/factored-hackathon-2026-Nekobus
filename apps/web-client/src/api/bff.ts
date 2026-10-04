// The same-origin BFF: the six chat routes of the orchestrator, and nothing else (ADR-0004, ADR-0013).
//
// It registers exactly the routes of `clientBffRoutes`. For each request it
//   1. validates the path parameter and the body with the route's own schemas (requests are strict),
//   2. forwards to the orchestrator route of the same name, on a path it builds itself, with the body
//      it parsed and the two headers it sets (`X-Forwarded-For`, content type), never the browser's,
//   3. validates the answer with the route's response schema and sends the parsed value on,
//   4. passes an error status and its `Retry-After` through.
// An upstream that cannot be reached, answers with a body outside the contract, or answers a 2xx that
// is not the route's success status, is a 503 `{"detail": "unavailable"}`.
//
// `blocks` stay raw (`RawBlock[]`): the browser runs `parseBlocks`. The BFF holds no token and no state.
// It never logs a body: the inbox response carries a live one-time code.

import {
  ApiErrorSchema,
  clientBffRoutes,
  ERROR_DETAIL,
  orchestratorChatRoutes,
  routePath,
  type RouteShape,
  type ValidationIssue,
} from "@pattern-blue/contracts";

type RouteName = keyof typeof clientBffRoutes;
type BffRoute = (typeof clientBffRoutes)[RouteName];

export interface BffOptions {
  /** Origin of the orchestrator, no trailing slash: `http://orchestrator:8080`. */
  orchestratorUrl: string;
  /** Injected in tests; defaults to the global `fetch`. */
  fetch?: typeof fetch;
  /** One line per problem, never a body. Defaults to `console.error`. */
  log?: (line: string) => void;
  /** A turn runs the LLM and the tools, so it gets a long timeout; the reads do not. */
  timeoutMs?: { turn: number; read: number };
}

export interface Bff {
  /** `clientAddress` is what `server.requestIP(req)` said, or null when the transport has none. */
  handle(req: Request, clientAddress: string | null): Promise<Response>;
}

export const DEFAULT_TIMEOUTS = { turn: 150_000, read: 15_000 } as const;

// `routePath` types its arguments per route; here the route is picked by name at run time, so one widening.
const pathOf = routePath as (route: RouteShape, params?: Record<string, string>) => string;

const ROUTE_NAMES = Object.keys(clientBffRoutes) as RouteName[];

interface CompiledRoute {
  name: RouteName;
  route: BffRoute;
  matcher: RegExp;
  paramNames: string[];
}

/** `/api/conversations/:id/messages` -> a regex with one capture per `:name`, exact (no trailing slash). */
function compile(name: RouteName): CompiledRoute {
  const route = clientBffRoutes[name];
  const paramNames: string[] = [];
  const source = route.pattern
    .split("/")
    .map((segment) => {
      if (!segment.startsWith(":")) return segment.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      paramNames.push(segment.slice(1));
      return "([^/]+)";
    })
    .join("/");
  return { name, route, matcher: new RegExp(`^${source}$`), paramNames };
}

const COMPILED = ROUTE_NAMES.map(compile);

const BASE_HEADERS = {
  // The inbox carries a live code: nothing here is cached by the browser or on the way.
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
} as const;

function json(status: number, body: unknown, extra: Record<string, string> = {}): Response {
  return Response.json(body, { status, headers: { ...BASE_HEADERS, ...extra } });
}

function unavailable(): Response {
  return json(503, { detail: ERROR_DETAIL.unavailable });
}

/** FastAPI's 422 shape, so the browser handles one error format. */
function validationError(
  where: "path" | "body",
  issues: ReadonlyArray<{ path: PropertyKey[]; message: string; code: string }>,
): Response {
  const detail: ValidationIssue[] = issues.map((issue) => ({
    loc: [where, ...issue.path.filter((part): part is string | number => typeof part !== "symbol")],
    msg: issue.message,
    type: issue.code,
  }));
  return json(422, { detail });
}

function singleIssue(where: "path" | "body", msg: string, type: string): Response {
  return json(422, { detail: [{ loc: [where], msg, type }] satisfies ValidationIssue[] });
}

export function createBff(options: BffOptions): Bff {
  const upstreamBase = options.orchestratorUrl.replace(/\/+$/, "");
  const doFetch = options.fetch ?? fetch;
  const log = options.log ?? ((line: string) => console.error(line));
  const timeouts = options.timeoutMs ?? DEFAULT_TIMEOUTS;

  async function handle(req: Request, clientAddress: string | null): Promise<Response> {
    const path = new URL(req.url).pathname;

    const onPath = COMPILED.flatMap((compiled) => {
      const match = compiled.matcher.exec(path);
      return match ? [{ compiled, match }] : [];
    });
    if (onPath.length === 0) return json(404, { detail: "not_found" });
    const hit = onPath.find(({ compiled }) => compiled.route.method === req.method);
    if (!hit) {
      const allow = [...new Set(onPath.map(({ compiled }) => compiled.route.method))].join(", ");
      return json(405, { detail: "method_not_allowed" }, { Allow: allow });
    }
    const { compiled, match } = hit;
    const { name, route } = compiled;

    // 1. path parameters
    const rawParams: Record<string, string> = {};
    for (const [index, paramName] of compiled.paramNames.entries()) {
      try {
        rawParams[paramName] = decodeURIComponent(match[index + 1] as string);
      } catch {
        return singleIssue("path", "Malformed path parameter", "invalid_path");
      }
    }
    let params: Record<string, string> = {};
    if ("params" in route) {
      const parsed = route.params.safeParse(rawParams);
      if (!parsed.success) return validationError("path", parsed.error.issues);
      params = parsed.data as Record<string, string>;
    }

    // 2. body
    let body: unknown;
    if ("body" in route) {
      const text = await req.text();
      let value: unknown;
      if (text.trim() !== "") {
        try {
          value = JSON.parse(text);
        } catch {
          return singleIssue("body", "Body is not valid JSON", "json_invalid");
        }
      }
      if ((value === undefined || value === null) && "bodyOptional" in route && route.bodyOptional) {
        body = undefined;
      } else {
        const parsed = route.body.safeParse(value);
        if (!parsed.success) return validationError("body", parsed.error.issues);
        body = parsed.data;
      }
    }

    // 3. forward, to a path this function builds from the orchestrator's own table
    const url = upstreamBase + pathOf(orchestratorChatRoutes[name], params);
    const headers: Record<string, string> = { Accept: "application/json" };
    if (clientAddress) headers["X-Forwarded-For"] = clientAddress;
    if (body !== undefined) headers["Content-Type"] = "application/json";

    let upstream: Response;
    let text: string;
    try {
      upstream = await doFetch(url, {
        method: route.method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        redirect: "manual",
        signal: AbortSignal.timeout(name === "sendMessage" ? timeouts.turn : timeouts.read),
      });
      text = await upstream.text();
    } catch (error) {
      log(`bff ${name}: orchestrator unreachable (${error instanceof Error ? error.name : "error"})`);
      return unavailable();
    }

    // 4. answer
    if (upstream.status >= 200 && upstream.status < 300) {
      if (upstream.status !== route.successStatus) {
        log(`bff ${name}: unexpected success status ${upstream.status}`);
        return unavailable();
      }
      let payload: unknown;
      try {
        payload = JSON.parse(text);
      } catch {
        log(`bff ${name}: upstream body is not JSON`);
        return unavailable();
      }
      const parsedBody = route.response.safeParse(payload);
      if (!parsedBody.success) {
        log(`bff ${name}: upstream body is outside the contract`);
        return unavailable();
      }
      return json(route.successStatus, parsedBody.data);
    }

    if (upstream.status < 400) {
      // A redirect or a 1xx/3xx is not part of the contract.
      log(`bff ${name}: unexpected upstream status ${upstream.status}`);
      return unavailable();
    }

    // An error status passes through with its `detail`; a body that is not one is a 503.
    let detail: unknown;
    try {
      const parsedError = ApiErrorSchema.safeParse(JSON.parse(text));
      if (parsedError.success) detail = parsedError.data.detail;
    } catch {
      // handled below
    }
    if (detail === undefined) {
      log(`bff ${name}: upstream error ${upstream.status} without a detail`);
      return unavailable();
    }
    const extra: Record<string, string> = {};
    const retryAfter = upstream.headers.get("retry-after");
    if (retryAfter !== null && retryAfter.length <= 64) extra["Retry-After"] = retryAfter;
    return json(upstream.status, { detail }, extra);
  }

  return { handle };
}
