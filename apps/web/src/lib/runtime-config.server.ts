/* Runtime configuration for the console, resolved on the server per request.
 *
 * The published web image is environment-agnostic: nothing about the API or
 * the brand is inlined at build time.
 *   SYNAPSE_API_URL           the API origin as BROWSERS reach it (required in prod)
 *   SYNAPSE_API_INTERNAL_URL  the API origin as THIS SERVER reaches it
 *                             (e.g. http://api:8000 in compose); defaults to the public one
 *
 * Branding is fetched from `${internal}/v1/branding` and memoised per process:
 * fresh for 60 s after a success, 5 s after a failure. Stale-while-revalidate:
 * once a memo exists, renders never wait on the API — an expired memo is served
 * as is while one shared background fetch refreshes it. Only the very first
 * render (no memo yet) awaits the fetch (≤ 2 s, then neutral DEFAULT_BRANDING).
 * Hand-rolled because the root layout is force-dynamic — the build never needs
 * the API — which also opts out of Next's fetch cache. Single resolution point:
 * per-org branding would hang off here later.
 *
 * Server-only: import it from server components and route handlers, never from
 * a "use client" module (it reads process.env and keeps a process-wide memo). */

import { DEFAULT_BRANDING, parseBranding, type Branding } from "./branding";

export interface RuntimeConfig {
  /** Public API origin, no trailing slash — what the browser calls. */
  apiUrl: string;
  branding: Branding;
}

const DEFAULT_API_URL = "http://localhost:8000";
const FETCH_TIMEOUT_MS = 2_000;
const TTL_OK_MS = 60_000;
const TTL_FAILED_MS = 5_000;

interface MemoEntry {
  key: string;
  branding: Branding;
  expiresAt: number;
}

let memo: MemoEntry | null = null;
let inflight: Promise<Branding> | null = null;
let lastFailureLogged = 0;

function trimSlash(url: string): string {
  return url.replace(/\/+$/, "");
}

function apiUrls(): { publicUrl: string; internalUrl: string } {
  const publicUrl = trimSlash(process.env.SYNAPSE_API_URL || DEFAULT_API_URL);
  const internalUrl = trimSlash(process.env.SYNAPSE_API_INTERNAL_URL || publicUrl);
  return { publicUrl, internalUrl };
}

async function fetchBranding(internalUrl: string): Promise<Branding> {
  const res = await fetch(`${internalUrl}/v1/branding`, {
    cache: "no-store",
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
  });
  if (!res.ok) throw new Error(`GET /v1/branding → ${res.status}`);
  return parseBranding(await res.json());
}

function refresh(internalUrl: string): Promise<Branding> {
  // One request at a time per process: concurrent renders share the fetch.
  inflight ??= fetchBranding(internalUrl)
    .then((branding) => {
      memo = { key: internalUrl, branding, expiresAt: Date.now() + TTL_OK_MS };
      return branding;
    })
    .catch((err: unknown) => {
      // Keep the last good branding through an outage; neutral only if none yet.
      const fallback = memo?.key === internalUrl ? memo.branding : DEFAULT_BRANDING;
      memo = { key: internalUrl, branding: fallback, expiresAt: Date.now() + TTL_FAILED_MS };
      if (Date.now() - lastFailureLogged > TTL_OK_MS) {
        lastFailureLogged = Date.now();
        console.warn(
          `[runtime-config] branding unavailable from ${internalUrl}: ${
            err instanceof Error ? err.message : String(err)
          } — using ${fallback === DEFAULT_BRANDING ? "neutral defaults" : "last known branding"}`,
        );
      }
      return fallback;
    })
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

async function resolveBranding(internalUrl: string): Promise<Branding> {
  const current = memo?.key === internalUrl ? memo : null;
  if (!current) return refresh(internalUrl);
  // Stale: answer now, revalidate in the background (refresh never rejects).
  if (current.expiresAt <= Date.now()) void refresh(internalUrl);
  return current.branding;
}

export async function getRuntimeConfig(): Promise<RuntimeConfig> {
  const { publicUrl, internalUrl } = apiUrls();
  return { apiUrl: publicUrl, branding: await resolveBranding(internalUrl) };
}
