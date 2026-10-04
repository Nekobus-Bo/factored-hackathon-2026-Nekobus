// The browser's side of the BFF: the six routes of `clientBffRoutes`, built from the same table the
// server registers. Each call validates the answer with the route's schema and returns a result, never
// throws: the machines branch on `kind`, and a network failure is the same as a 503.
//
//   ok            the route's success status, body inside the contract
//   rate_limited  429; `retryAfterSeconds` from the header (60 when it is missing or unreadable)
//   not_found     404: the conversation is gone (the orchestrator keeps it for a limited time)
//   unavailable   everything else: 5xx, 409, a body outside the contract, no network

import {
  clientBffRoutes,
  routePath,
  type CapabilitiesResponse,
  type CreateConversationRequest,
  type CreateConversationResponse,
  type FeedbackResponse,
  type InboxResponse,
  type SendFeedbackRequest,
  type SendMessageRequest,
  type SendMessageResponse,
  type TranscriptResponse,
} from "@pattern-blue/contracts";

export type ApiFailure =
  | { ok: false; kind: "rate_limited"; retryAfterSeconds: number }
  | { ok: false; kind: "not_found" }
  | { ok: false; kind: "unavailable" };

export type ApiResult<T> = { ok: true; data: T } | ApiFailure;

export interface ApiClient {
  createConversation(body: CreateConversationRequest): Promise<ApiResult<CreateConversationResponse>>;
  sendMessage(conversationId: string, body: SendMessageRequest): Promise<ApiResult<SendMessageResponse>>;
  getTranscript(conversationId: string): Promise<ApiResult<TranscriptResponse>>;
  getInbox(conversationId: string): Promise<ApiResult<InboxResponse>>;
  sendFeedback(conversationId: string, body: SendFeedbackRequest): Promise<ApiResult<FeedbackResponse>>;
  /** Whether detective mode is on (ADR-0019): turns then carry their trace. */
  getCapabilities(): Promise<ApiResult<CapabilitiesResponse>>;
}

export const DEFAULT_RETRY_AFTER_SECONDS = 60;
const MAX_RETRY_AFTER_SECONDS = 24 * 60 * 60;

/** `Retry-After` is delta-seconds or an HTTP date. Anything else asks for the default wait. */
export function parseRetryAfter(value: string | null, nowMs: number = Date.now()): number {
  const text = value?.trim();
  if (!text) return DEFAULT_RETRY_AFTER_SECONDS;
  let seconds: number;
  if (/^\d+$/.test(text)) {
    seconds = Number(text);
  } else {
    const at = Date.parse(text);
    if (Number.isNaN(at)) return DEFAULT_RETRY_AFTER_SECONDS;
    seconds = Math.ceil((at - nowMs) / 1000);
  }
  return Math.min(MAX_RETRY_AFTER_SECONDS, Math.max(1, seconds));
}

export interface ApiClientOptions {
  fetch?: typeof fetch;
  /** Prefix of every URL; empty for the same origin. */
  baseUrl?: string;
  now?: () => number;
}

export function createApiClient(options: ApiClientOptions = {}): ApiClient {
  const now = options.now ?? Date.now;
  const baseUrl = options.baseUrl ?? "";

  async function call<T>(
    route: {
      method: string;
      successStatus: number;
      response: { safeParse(input: unknown): { success: true; data: unknown } | { success: false } };
    },
    path: string,
    body?: unknown,
  ): Promise<ApiResult<T>> {
    let response: Response;
    try {
      response = await (options.fetch ?? fetch)(baseUrl + path, {
        method: route.method,
        headers: body === undefined ? undefined : { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
        // The inbox holds a live code and the transcript changes while an agent writes.
        cache: "no-store",
      });
    } catch {
      return { ok: false, kind: "unavailable" };
    }

    if (response.status === route.successStatus) {
      try {
        const parsed = route.response.safeParse(await response.json());
        return parsed.success ? { ok: true, data: parsed.data as T } : { ok: false, kind: "unavailable" };
      } catch {
        return { ok: false, kind: "unavailable" };
      }
    }
    if (response.status === 429) {
      return { ok: false, kind: "rate_limited", retryAfterSeconds: parseRetryAfter(response.headers.get("retry-after"), now()) };
    }
    if (response.status === 404) return { ok: false, kind: "not_found" };
    return { ok: false, kind: "unavailable" };
  }

  return {
    createConversation: (body) =>
      call(clientBffRoutes.createConversation, routePath(clientBffRoutes.createConversation), body),
    sendMessage: (id, body) =>
      call(clientBffRoutes.sendMessage, routePath(clientBffRoutes.sendMessage, { id }), body),
    getTranscript: (id) => call(clientBffRoutes.getTranscript, routePath(clientBffRoutes.getTranscript, { id })),
    getInbox: (id) => call(clientBffRoutes.getInbox, routePath(clientBffRoutes.getInbox, { id })),
    sendFeedback: (id, body) =>
      call(clientBffRoutes.sendFeedback, routePath(clientBffRoutes.sendFeedback, { id }), body),
    getCapabilities: () => call(clientBffRoutes.getCapabilities, routePath(clientBffRoutes.getCapabilities)),
  };
}
