// A route is data: method, path pattern and the schemas of its parts. Servers register exactly the
// routes of a table (a closed list; a BFF never forwards an arbitrary path), and clients build their
// URLs from the same table. tests/routes.test.ts pins each table to the list in the front-end spec.

import type { z } from "zod";

export type HttpMethod = "GET" | "POST" | "PUT" | "DELETE";

export interface RouteShape {
  readonly method: HttpMethod;
  /** Path with `:name` segments, the syntax `Bun.serve` routes use. */
  readonly pattern: string;
  /** The status a success carries in this contract. Any other 2xx from an upstream is a mismatch to report. */
  readonly successStatus: number;
  /** Path parameters: an object schema with one key per `:name` in the pattern. */
  readonly params?: z.ZodObject;
  readonly query?: z.ZodObject;
  readonly body?: z.ZodType;
  /** The body may be missing altogether (the request then means `{}`). */
  readonly bodyOptional?: boolean;
  /** Absent when the success has no body (204). */
  readonly response?: z.ZodType;
}

/** Identity function that keeps the literal type of a route, so its schemas stay inferable. */
export function defineRoute<const T extends RouteShape>(route: T): T {
  return route;
}

/** The arguments `routePath` needs: the path parameters, when the route has any. */
export type PathArgs<T extends RouteShape> = T extends { params: infer P extends z.ZodObject }
  ? [params: z.input<P>]
  : [];

const PARAM_NAME = /:([A-Za-z_][A-Za-z0-9_]*)/g;

/** The `:name` segments of a pattern, in order. */
export function patternParams(pattern: string): string[] {
  return [...pattern.matchAll(PARAM_NAME)].map((match) => match[1] as string);
}

/**
 * Fill a route's pattern. Each value is URL-encoded, so a value can never add a segment; the caller
 * still validates it with the route's `params` schema before it builds an upstream path.
 */
export function routePath<T extends RouteShape>(route: T, ...args: PathArgs<T>): string {
  const params = ((args as readonly unknown[])[0] ?? {}) as Record<string, unknown>;
  return route.pattern.replace(PARAM_NAME, (_match, name: string) => {
    const value = params[name];
    if (typeof value !== "string" || value === "") {
      throw new TypeError(`route ${route.method} ${route.pattern} needs the path parameter "${name}"`);
    }
    return encodeURIComponent(value);
  });
}

type QueryValue = string | number | boolean | undefined;

/** `?a=1&b=x&b=y`, or the empty string. A list repeats its key, the way FastAPI reads `status=A&status=B`. */
export function toQueryString(query: Record<string, QueryValue | readonly QueryValue[]>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    for (const item of Array.isArray(value) ? value : [value]) {
      if (item !== undefined) search.append(key, String(item));
    }
  }
  const text = search.toString();
  return text === "" ? "" : `?${text}`;
}

/** The inverse, for a server: a key that repeats becomes a list, a key that appears once stays a string. */
export function queryFromSearchParams(search: URLSearchParams): Record<string, string | string[]> {
  const query: Record<string, string | string[]> = {};
  for (const key of new Set(search.keys())) {
    const values = search.getAll(key);
    query[key] = values.length === 1 ? (values[0] as string) : values;
  }
  return query;
}
