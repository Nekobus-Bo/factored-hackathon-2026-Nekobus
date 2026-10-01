// A `fetch` for the machine tests: routes answered from a table, every call recorded.

export interface Call {
  method: string;
  path: string;
  search: string;
  headers: Record<string, string>;
  body: unknown;
}

export type Handler = (call: Call, params: Record<string, string>) => Response | Promise<Response>;

export const json = (body: unknown, status = 200, headers: Record<string, string> = {}) => Response.json(body, { status, headers });
export const noContent = () => new Response(null, { status: 204 });

function compile(route: string) {
  const [method, pattern] = route.split(" ") as [string, string];
  const segments = pattern.split("/");
  return (callMethod: string, path: string): Record<string, string> | null => {
    if (callMethod !== method) return null;
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

export function fakeFetch(initial: Record<string, Handler>) {
  const handlers = new Map(Object.entries(initial));
  const calls: Call[] = [];

  const fetch = async (input: string, init: RequestInit): Promise<Response> => {
    const url = new URL(input, "http://backoffice.test");
    const call: Call = {
      method: init.method ?? "GET",
      path: url.pathname,
      search: url.search,
      headers: Object.fromEntries(Object.entries((init.headers ?? {}) as Record<string, string>)),
      body: typeof init.body === "string" ? JSON.parse(init.body) : undefined,
    };
    calls.push(call);
    for (const [route, handler] of handlers) {
      const params = compile(route)(call.method, call.path);
      if (params) return handler(call, params);
    }
    return json({ detail: "not_found" }, 404);
  };

  return {
    fetch,
    calls,
    /** Replace or add the answer of one route. */
    on: (route: string, handler: Handler) => void handlers.set(route, handler),
    /** How many calls went to `METHOD /path`. */
    count: (route: string) => {
      const match = compile(route);
      return calls.filter((call) => match(call.method, call.path) !== null).length;
    },
    /** The calls to `METHOD /path`, in order. */
    to: (route: string) => {
      const match = compile(route);
      return calls.filter((call) => match(call.method, call.path) !== null);
    },
  };
}

/** Wait until a condition holds, polling every few milliseconds. */
export async function until(condition: () => boolean, timeoutMs = 2000): Promise<void> {
  const start = Date.now();
  while (!condition()) {
    if (Date.now() - start > timeoutMs) throw new Error("timed out waiting for a condition");
    await Bun.sleep(5);
  }
}
