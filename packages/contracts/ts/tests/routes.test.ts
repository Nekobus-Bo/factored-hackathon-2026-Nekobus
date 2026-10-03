import { describe, expect, test } from "bun:test";
import {
  backofficeBffRoutes,
  bankingAdminRoutes,
  clientBffRoutes,
  orchestratorAgentRoutes,
  orchestratorChatRoutes,
  patternParams,
  queryFromSearchParams,
  routePath,
  toQueryString,
  type RouteShape,
} from "../index";
import { CONVERSATION_ID, HANDOFF_REF, SESSION_REF } from "./fixtures";

const listOf = (table: Record<string, RouteShape>): string[] =>
  Object.values(table)
    .map((route) => `${route.method} ${route.pattern}`)
    .sort();

// The closed lists of the front-end spec ("HTTP contract"). A route added to a table without being
// added here, or the other way round, fails: a BFF forwards nothing that is not on its list.
describe("the route tables are the spec's closed lists", () => {
  test("orchestrator chat API", () => {
    expect(listOf(orchestratorChatRoutes)).toEqual(
      [
        "POST /v1/conversations",
        "POST /v1/conversations/:id/messages",
        "GET /v1/conversations/:id",
        "GET /v1/conversations/:id/inbox",
        "POST /v1/conversations/:id/feedback",
      ].sort(),
    );
  });

  test("orchestrator agent API", () => {
    expect(listOf(orchestratorAgentRoutes)).toEqual(
      [
        "GET /v1/agent/sessions/:session_ref/conversation",
        "GET /v1/agent/conversations/:id",
        "POST /v1/agent/conversations/:id/takeover",
        "POST /v1/agent/conversations/:id/messages",
      ].sort(),
    );
  });

  test("banking-core admin API", () => {
    expect(listOf(bankingAdminRoutes)).toEqual(
      [
        "GET /v1/admin/handoffs",
        "GET /v1/admin/handoffs/:handoff_ref",
        "POST /v1/admin/handoffs/:handoff_ref/claim",
        "GET /v1/admin/metrics",
        "GET /v1/admin/policy-config",
        "PUT /v1/admin/policy-config",
        "GET /v1/admin/tool-policy",
        "PUT /v1/admin/tool-policy",
        "POST /v1/admin/demo/reset-fixtures",
      ].sort(),
    );
  });

  test("web-client BFF", () => {
    expect(listOf(clientBffRoutes)).toEqual(
      [
        "POST /api/conversations",
        "POST /api/conversations/:id/messages",
        "GET /api/conversations/:id",
        "GET /api/conversations/:id/inbox",
        "POST /api/conversations/:id/feedback",
      ].sort(),
    );
  });

  test("web-backoffice BFF", () => {
    expect(listOf(backofficeBffRoutes)).toEqual(
      [
        "POST /api/session",
        "DELETE /api/session",
        "GET /api/session",
        "GET /api/handoffs",
        "GET /api/handoffs/:ref",
        "POST /api/handoffs/:ref/claim",
        "GET /api/conversations/:id",
        "POST /api/conversations/:id/messages",
        "GET /api/policy-config",
        "PUT /api/policy-config",
        "GET /api/tool-policy",
        "PUT /api/tool-policy",
        "POST /api/demo/reset",
        "GET /api/metrics",
      ].sort(),
    );
  });
});

describe("every route is well formed", () => {
  const tables: Record<string, Record<string, RouteShape>> = {
    orchestratorChatRoutes,
    orchestratorAgentRoutes,
    bankingAdminRoutes,
    clientBffRoutes,
    backofficeBffRoutes,
  };

  for (const [tableName, table] of Object.entries(tables)) {
    for (const [name, route] of Object.entries(table)) {
      test(`${tableName}.${name}`, () => {
        // Upstream services live under /v1, the BFFs under /api.
        expect(route.pattern.startsWith(tableName.endsWith("BffRoutes") ? "/api/" : "/v1/")).toBe(true);
        // One params key per `:name`.
        expect(Object.keys(route.params?.shape ?? {}).sort()).toEqual(patternParams(route.pattern).sort());
        // Only writes have a body.
        if (route.body !== undefined) expect(["POST", "PUT"]).toContain(route.method);
        // A 204 has no body; anything else says what it returns.
        expect(route.response === undefined).toBe(route.successStatus === 204);
      });
    }
  }
});

describe("the web-client BFF maps 1:1 to the orchestrator chat routes", () => {
  for (const name of Object.keys(clientBffRoutes) as (keyof typeof clientBffRoutes)[]) {
    test(name, () => {
      const bff = clientBffRoutes[name];
      const upstream = orchestratorChatRoutes[name];
      expect(bff.method).toBe(upstream.method);
      expect(bff.pattern as string).toBe(upstream.pattern.replace("/v1/", "/api/"));
      expect(bff.successStatus).toBe(upstream.successStatus);
      expect(bff.response).toBe(upstream.response);
      expect("body" in bff ? bff.body : undefined).toBe("body" in upstream ? upstream.body : undefined);
    });
  }
});

describe("routePath", () => {
  test("fills the pattern", () => {
    expect(routePath(orchestratorChatRoutes.createConversation)).toBe("/v1/conversations");
    expect(routePath(orchestratorChatRoutes.getInbox, { id: CONVERSATION_ID })).toBe(`/v1/conversations/${CONVERSATION_ID}/inbox`);
    expect(routePath(backofficeBffRoutes.claimHandoff, { ref: HANDOFF_REF })).toBe(`/api/handoffs/${HANDOFF_REF}/claim`);
    expect(routePath(orchestratorAgentRoutes.conversationForSession, { session_ref: SESSION_REF })).toBe(
      `/v1/agent/sessions/${SESSION_REF}/conversation`,
    );
  });

  test("a value cannot add a segment or a query", () => {
    expect(routePath(orchestratorChatRoutes.getTranscript, { id: "../admin?x=1" })).toBe(
      "/v1/conversations/..%2Fadmin%3Fx%3D1",
    );
  });

  test("a missing or empty parameter is an error", () => {
    // @ts-expect-error the route needs its `id`
    expect(() => routePath(orchestratorChatRoutes.getTranscript)).toThrow(TypeError);
    expect(() => routePath(orchestratorChatRoutes.getTranscript, { id: "" })).toThrow(TypeError);
  });

  test("the parameters are typed", () => {
    // Checked by `tsc --noEmit` (make web-check); never called, since the calls are wrong on purpose.
    const compileTimeOnly = () => {
      // @ts-expect-error the parameter is `id`, not `conversation_id`
      routePath(orchestratorChatRoutes.getTranscript, { conversation_id: CONVERSATION_ID });
      // @ts-expect-error a route without parameters takes none
      routePath(orchestratorChatRoutes.createConversation, { id: CONVERSATION_ID });
    };
    expect(compileTimeOnly).toBeInstanceOf(Function);
  });
});

describe("query strings", () => {
  test("a list repeats its key, and undefined is left out", () => {
    expect(toQueryString({})).toBe("");
    expect(toQueryString({ hours: undefined })).toBe("");
    expect(toQueryString({ hours: 48 })).toBe("?hours=48");
    expect(toQueryString({ status: ["QUEUED", "ASSIGNED"] })).toBe("?status=QUEUED&status=ASSIGNED");
  });

  test("a server reads them back", () => {
    expect(queryFromSearchParams(new URLSearchParams("status=QUEUED&status=ASSIGNED&hours=6"))).toEqual({
      status: ["QUEUED", "ASSIGNED"],
      hours: "6",
    });
    expect(queryFromSearchParams(new URLSearchParams(""))).toEqual({});
    const parsed = backofficeBffRoutes.listHandoffs.query.parse(queryFromSearchParams(new URLSearchParams("status=QUEUED")));
    expect(parsed.status).toEqual(["QUEUED"]);
    expect(backofficeBffRoutes.getMetrics.query.parse(queryFromSearchParams(new URLSearchParams("hours=6"))).hours).toBe(6);
  });
});
