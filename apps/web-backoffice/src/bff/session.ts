// The agent session: a cookie that carries `{agent_ref, exp}` and an HMAC-SHA256 signature over it.
//
//   pb_session=<base64url(json payload)>.<base64url(hmac-sha256(secret, base64url(json payload)))>
//
// There is no server-side session store: the signature is the proof, the expiry is inside the signed
// payload, and a tampered or expired cookie is simply "no session". Credentials and signatures are
// compared in constant time.

import { createHash, createHmac, timingSafeEqual } from "node:crypto";
import { AgentRefSchema } from "@pattern-blue/contracts";
import { z } from "zod";

export const SESSION_COOKIE = "pb_session";

export const SessionPayloadSchema = z.strictObject({
  agent_ref: AgentRefSchema,
  /** Expiry, seconds since the epoch. */
  exp: z.number().int().positive(),
});
export type SessionPayload = z.infer<typeof SessionPayloadSchema>;

// --- Constant-time comparison -------------------------------------------------------------------------

export type Compare = (supplied: string, expected: string) => boolean;

/**
 * Equality whose running time does not depend on where two strings differ or on their lengths: both are
 * hashed to 32 bytes first, then compared with `timingSafeEqual`.
 */
export const safeEqual: Compare = (supplied, expected) =>
  timingSafeEqual(createHash("sha256").update(supplied).digest(), createHash("sha256").update(expected).digest());

/**
 * Check a login. Both fields are always compared, so a wrong e-mail takes as long as a wrong password.
 * The e-mail is case-insensitive (domains are); the password is exact.
 */
export function credentialsMatch(
  supplied: { email: string; password: string },
  expected: { email: string; password: string },
  compare: Compare = safeEqual,
): boolean {
  const emailMatches = compare(supplied.email.trim().toLowerCase(), expected.email.trim().toLowerCase());
  const passwordMatches = compare(supplied.password, expected.password);
  return emailMatches && passwordMatches;
}

// --- Signing ------------------------------------------------------------------------------------------

function base64url(input: string | Buffer): string {
  return Buffer.from(input).toString("base64url");
}

function signature(body: string, secret: string): Buffer {
  return createHmac("sha256", secret).update(body).digest();
}

/** The cookie value for a session. */
export function signSession(payload: SessionPayload, secret: string): string {
  const body = base64url(JSON.stringify({ agent_ref: payload.agent_ref, exp: payload.exp }));
  return `${body}.${base64url(signature(body, secret))}`;
}

/**
 * The session a cookie value proves, or null: a missing value, a malformed one, a signature that does
 * not match (tampered, or signed with another secret), a payload of the wrong shape, or an expired one.
 */
export function readSession(value: string | undefined | null, secret: string, nowMs: number): SessionPayload | null {
  if (!value) return null;
  const parts = value.split(".");
  if (parts.length !== 2) return null;
  const [body, provided] = parts as [string, string];

  const expected = signature(body, secret);
  const supplied = Buffer.from(provided, "base64url");
  // `timingSafeEqual` throws on a length mismatch, and the length of a MAC is public anyway.
  if (supplied.length !== expected.length || !timingSafeEqual(supplied, expected)) return null;

  let json: unknown;
  try {
    json = JSON.parse(Buffer.from(body, "base64url").toString("utf8"));
  } catch {
    return null;
  }
  const parsed = SessionPayloadSchema.safeParse(json);
  if (!parsed.success) return null;
  if (parsed.data.exp * 1000 <= nowMs) return null;
  return parsed.data;
}

// --- Cookie header ------------------------------------------------------------------------------------

/** The value of one cookie in a `Cookie` request header. */
export function cookieValue(header: string | null, name: string): string | undefined {
  if (!header) return undefined;
  for (const part of header.split(";")) {
    const separator = part.indexOf("=");
    if (separator === -1) continue;
    if (part.slice(0, separator).trim() === name) return part.slice(separator + 1).trim();
  }
  return undefined;
}

/** `Set-Cookie` for a new session: HttpOnly, SameSite=Strict, Path=/, Secure in production. */
export function sessionSetCookie(value: string, options: { secure: boolean; maxAgeSeconds: number }): string {
  return [
    `${SESSION_COOKIE}=${value}`,
    "Path=/",
    "HttpOnly",
    "SameSite=Strict",
    `Max-Age=${options.maxAgeSeconds}`,
    ...(options.secure ? ["Secure"] : []),
  ].join("; ");
}

/** `Set-Cookie` that removes the session (logout). */
export function sessionClearCookie(options: { secure: boolean }): string {
  return sessionSetCookie("", { secure: options.secure, maxAgeSeconds: 0 });
}
