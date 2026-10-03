// Fake banking-core and orchestrator servers: real `Bun.serve` instances on ephemeral ports that follow
// the contract of docs/front-ends.md, answer with the fixtures, check the bearer token the way the real
// services do and record every request they get. A test overrides one route with `fake.on(...)`.

import {
  AGENT_EMAIL,
  CONVERSATION_ID,
  agentMessageResponse,
  backofficeDetail,
  claimedDetail,
  closedDetail,
  demoReset,
  escalatedDetail,
  handoffDetail,
  handoffItems,
  metrics,
  policyConfig,
  takeoverResponse,
  toolPolicy,
  transcript,
} from "./fixtures";

export interface RecordedRequest {
  method: string;
  path: string;
  search: string;
  headers: Record<string, string>;
  /** Parsed JSON body, or undefined when there was none. */
  body: unknown;
}

export type Responder = (request: RecordedRequest, params: Record<string, string>) => Response | Promise<Response>;

export interface FakeService {
  url: string;
  token: string;
  requests: RecordedRequest[];
  /** Replace the answer of one route, e.g. `on("POST /v1/agent/conversations/:id/takeover", () => ...)`. */
  on(route: string, responder: Responder): void;
  stop(): void;
}

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) => Response.json(body, { status, headers });

function matcher(route: string) {
  const [method, pattern] = route.split(" ") as [string, string];
  const segments = pattern.split("/");
  return (requestMethod: string, path: string): Record<string, string> | null => {
    if (requestMethod !== method) return null;
    const actual = path.split("/");
    if (actual.length !== segments.length) return null;
    const params: Record<string, string> = {};
    for (const [index, segment] of segments.entries()) {
      if (segment.startsWith(":")) params[segment.slice(1)] = decodeURIComponent(actual[index] as string);
      else if (segment !== actual[index]) return null;
    }
    return params;
  };
}

function startFake(token: string, defaults: Record<string, Responder>): FakeService {
  const responders = new Map<string, Responder>(Object.entries(defaults));
  const requests: RecordedRequest[] = [];

  const server = Bun.serve({
    port: 0,
    async fetch(req) {
      const url = new URL(req.url);
      const text = await req.text();
      const recorded: RecordedRequest = {
        method: req.method,
        path: url.pathname,
        search: url.search,
        headers: Object.fromEntries(req.headers.entries()),
        body: text === "" ? undefined : JSON.parse(text),
      };
      requests.push(recorded);

      if (req.headers.get("authorization") !== `Bearer ${token}`) {
        return json({ detail: "Invalid token" }, 401, { "WWW-Authenticate": "Bearer" });
      }
      for (const [route, responder] of responders) {
        const params = matcher(route)(req.method, url.pathname);
        if (params) return responder(recorded, params);
      }
      return json({ detail: "Not Found" }, 404);
    },
  });

  return {
    url: `http://127.0.0.1:${server.port}`,
    token,
    requests,
    on: (route, responder) => void responders.set(route, responder),
    stop: () => void server.stop(true),
  };
}

export function startFakeBankingCore(token = "test-admin-token"): FakeService {
  return startFake(token, {
    "GET /v1/admin/handoffs": (request) => {
      const statuses = new URLSearchParams(request.search).getAll("status");
      const wanted = statuses.length > 0 ? statuses : ["QUEUED", "ASSIGNED"];
      return json({ items: handoffItems().filter((item) => wanted.includes(item.status)) });
    },
    "GET /v1/admin/handoffs/:handoff_ref": (_request, params) => {
      const item = handoffItems().find((candidate) => candidate.handoff_ref === params.handoff_ref);
      return item ? json(handoffDetail(item)) : json({ detail: "Handoff not found" }, 404);
    },
    "POST /v1/admin/handoffs/:handoff_ref/claim": (request) =>
      json(claimedDetail((request.body as { agent_ref: string }).agent_ref)),
    "POST /v1/admin/handoffs/:handoff_ref/close": (request) => {
      const body = request.body as { agent_ref: string; outcome: "APPROVED" | "REJECTED" };
      return json(closedDetail(body.outcome, body.agent_ref));
    },
    "POST /v1/admin/handoffs/:handoff_ref/escalate": () => json(escalatedDetail()),
    "GET /v1/admin/metrics": (request) => json(metrics(Number(new URLSearchParams(request.search).get("hours") ?? 24))),
    "GET /v1/admin/policy-config": () => json(policyConfig()),
    "PUT /v1/admin/policy-config": (request) => {
      const body = request.body as { amount_mode: "flag" | "block"; thresholds_minor: Record<string, number> };
      return json({ ...body, version: policyConfig().version + 1 });
    },
    "GET /v1/admin/tool-policy": () => json(toolPolicy()),
    "PUT /v1/admin/tool-policy": (request) => {
      const current = toolPolicy();
      const changes = (request.body as { tools: Record<string, string[]> }).tools;
      const tools = { ...current.tools, ...changes };
      return json({
        ...current,
        version: current.version + 1,
        tools,
        disabled: Object.entries(tools).filter(([, states]) => states.length === 0).map(([name]) => name).sort(),
      });
    },
    "POST /v1/admin/demo/reset-fixtures": () => json(demoReset()),
  });
}

export function startFakeOrchestrator(token = "test-agent-token"): FakeService {
  /** Whether the conversation is taken over, and by whom: enough state for a takeover to be observable. */
  let holder: string | null = null;

  return startFake(token, {
    "GET /v1/agent/sessions/:session_ref/conversation": () => json({ conversation_id: CONVERSATION_ID }),
    "GET /v1/agent/conversations/:id": () =>
      json(
        transcript({
          takeover: holder ? { active: true, since: new Date().toISOString(), agent_ref: holder } : { active: false, since: null, agent_ref: null },
          withAgentMessage: holder !== null,
        }),
      ),
    "POST /v1/agent/conversations/:id/takeover": (request) => {
      const agentRef = (request.body as { agent_ref: string }).agent_ref;
      if (holder && holder !== agentRef) return json({ detail: "taken_over_by_another_agent" }, 409);
      holder = agentRef;
      return json(takeoverResponse(agentRef));
    },
    "POST /v1/agent/conversations/:id/release": (request) => {
      const agentRef = (request.body as { agent_ref: string }).agent_ref;
      if (holder && holder !== agentRef) return json({ detail: "taken_over_by_another_agent" }, 409);
      const since = new Date().toISOString();
      const wasTaken = holder !== null;
      holder = null;
      return json({ conversation_id: CONVERSATION_ID, takeover: wasTaken ? { active: true, since, agent_ref: null } : { active: false, since: null, agent_ref: null } });
    },
    "POST /v1/agent/conversations/:id/messages": (request) => {
      const agentRef = request.headers["x-agent-ref"];
      if (!holder || holder !== agentRef) return json({ detail: "no_active_takeover" }, 409);
      return json(agentMessageResponse(String((request.body as { text: string }).text)));
    },
  });
}

export { AGENT_EMAIL, backofficeDetail };
