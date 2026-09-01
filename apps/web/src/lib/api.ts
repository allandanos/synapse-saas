/* API client: single 401→refresh→retry, active org via X-Org-Id, typed helpers.
 * Access token lives in memory only; the refresh token is an httpOnly cookie. */

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

let accessToken: string | null = null;
let orgId: string | null = null;

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function setOrgId(id: string | null) {
  orgId = id;
}

export class ApiError extends Error {
  status: number;
  body: Record<string, unknown>;

  constructor(status: number, body: Record<string, unknown>) {
    super(String(body.detail ?? body.title ?? `API error ${status}`));
    this.status = status;
    this.body = body;
  }
}

async function rawRequest(path: string, init: RequestInit): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (orgId) headers.set("X-Org-Id", orgId);
  return fetch(`${API_URL}${path}`, { ...init, headers, credentials: "include" });
}

let refreshPromise: Promise<boolean> | null = null;

export async function refreshTokens(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        const res = await fetch(`${API_URL}/v1/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
          credentials: "include",
        });
        if (!res.ok) return false;
        const data = await res.json();
        accessToken = data.access_token;
        return true;
      } catch {
        return false;
      } finally {
        setTimeout(() => (refreshPromise = null), 0);
      }
    })();
  }
  return refreshPromise;
}

export async function api<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  let res = await rawRequest(path, init);

  if (res.status === 401 && !path.startsWith("/v1/auth/")) {
    const refreshed = await refreshTokens();
    if (refreshed) res = await rawRequest(path, init);
  }

  if (res.status === 204) return undefined as T;

  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, body);
  return body as T;
}

/* ── Shared types ────────────────────────────────────────────────────────── */

export interface Org {
  id: string;
  slug: string;
  name: string;
  role_keys: string[];
}

export interface Me {
  id: string;
  email: string;
  display_name: string;
  is_platform_admin: boolean;
  orgs: Org[];
}

export interface Plan {
  id: string;
  key: string;
  name: string;
  description: string | null;
  price_cents: number | null;
  currency: string;
  interval: string | null;
  features: { feature_key: string; enabled: boolean }[];
  limits: { metric: string; limit_value: number | null; soft_limit_ratio: number | null }[];
}

export interface Subscription {
  id: string;
  status: string;
  current_period_end: string;
  plan: Plan;
  plan_snapshot: { key: string; name: string };
}

export interface Entitlements {
  plan_key: string | null;
  subscription_status: string | null;
  features: string[];
  limits: Record<string, { value: number | null; soft_limit_ratio: number | null }>;
}

export interface UsageCheck {
  metric: string;
  used: number;
  limit: number | null;
  remaining: number | null;
  within_limit: boolean;
  soft_limit: number | null;
  soft_limit_breached: boolean;
}

export interface Member {
  id: string;
  email: string | null;
  invited_email: string | null;
  display_name: string | null;
  status: string;
  role_keys: string[];
}

export interface Invoice {
  id: string;
  currency: string;
  total_cents: number;
  status: string;
  hosted_url: string | null;
  paid_at: string | null;
  created_at: string;
}

export function formatMoney(cents: number | null, currency: string): string {
  if (cents === null) return "Custom";
  const symbols: Record<string, string> = { PHP: "₱", USD: "$", EUR: "€" };
  const symbol = symbols[currency] ?? `${currency} `;
  return `${symbol}${(cents / 100).toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
}

export function formatBytes(bytes: number): string {
  if (bytes >= 1073741824) return `${(bytes / 1073741824).toFixed(1)} GB`;
  if (bytes >= 1048576) return `${(bytes / 1048576).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

export function formatMetric(metric: string, value: number): string {
  return metric === "storage_bytes" ? formatBytes(value) : value.toLocaleString();
}
