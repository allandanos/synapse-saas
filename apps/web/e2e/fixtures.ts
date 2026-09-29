/**
 * Shared fixtures: talk to the real API to set up state, drive the console UI
 * for the behavior under test. One unique email per run — tests are
 * re-runnable against a shared dev stack.
 */
import { test as base, expect, type APIRequestContext, type Page } from "@playwright/test";

export const API_URL = process.env.E2E_API_URL ?? "http://localhost:8000";

/** Deterministic unique suffix per run (stable across tests in the run). */
const RUN = Date.now().toString(36);

export function emailFor(label: string): string {
  return `e2e-${RUN}-${label}@example.com`;
}

export interface StackContext {
  accessToken: string;
  refreshToken: string;
  orgId: string;
  orgSlug: string;
  email: string;
}

/**
 * Register a user and create their org via the API (the flows under test are
 * the console journeys, not signup mechanics — covered separately).
 */
export async function createStackContext(
  request: APIRequestContext,
  label: string,
): Promise<StackContext> {
  const email = emailFor(label);
  const password = "password12345";

  const reg = await request.post(`${API_URL}/v1/auth/register`, {
    data: { email, password, display_name: `E2E ${label}` },
  });
  // Surface the RFC7807 body on failure — "create org 401" alone hides the why.
  const regBody = (await reg.json().catch(() => ({}))) as {
    tokens?: { access_token: string; refresh_token: string };
  };
  expect(
    reg.ok(),
    `register ${email}: ${reg.status()} ${JSON.stringify(regBody).slice(0, 300)}`,
  ).toBeTruthy();
  expect(
    regBody.tokens?.access_token,
    `register returned no access token: ${reg.status()}`,
  ).toBeTruthy();

  const org = await request.post(`${API_URL}/v1/orgs`, {
    headers: { Authorization: `Bearer ${regBody.tokens!.access_token}` },
    data: { name: `E2E ${label} Org` },
  });
  const orgBody = (await org.json().catch(() => ({}))) as {
    id?: string;
    slug?: string;
    detail?: string;
  };
  expect(
    org.ok(),
    `create org: ${org.status()} ${JSON.stringify(orgBody).slice(0, 300)}`,
  ).toBeTruthy();
  expect(orgBody.id, "org id").toBeTruthy();

  return {
    accessToken: regBody.tokens!.access_token,
    refreshToken: regBody.tokens!.refresh_token,
    orgId: orgBody.id!,
    orgSlug: orgBody.slug ?? "",
    email,
  };
}

/** Log the browser into the console by planting the refresh cookie + reloading.
 *
 * Targets localhost explicitly — e2e runs against the local stack. The API's
 * CORS allows the console origin's credentials, and the auth context's silent
 * refresh turns the cookie into an access token on mount.
 */
export async function loginConsole(page: Page, ctx: StackContext): Promise<void> {
  // baseURL is always set by the config; the page may still be about:blank.
  const domain = new URL(
    (page as unknown as { _baseUrl?: string })._baseUrl ??
      process.env.E2E_BASE_URL ??
      "http://localhost:3000",
  ).hostname;
  await page.context().addCookies([
    {
      name: "synapse_rt",
      value: ctx.refreshToken,
      domain,
      path: "/",
      httpOnly: true,
      sameSite: "Lax",
    },
    { name: "synapse_org", value: ctx.orgId, domain, path: "/" },
  ]);
  await page.goto("/dashboard");
  await page.waitForLoadState("networkidle");
}

/** Seed the session via the console's own login form (exercises the real flow). */
export async function loginViaUi(page: Page, email: string, password: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/dashboard|onboarding/);
}

/** Convenience: authenticated API helper bound to a context. */
export function api(request: APIRequestContext, ctx: StackContext) {
  return {
    async post(path: string, data: unknown) {
      return request.post(`${API_URL}${path}`, {
        headers: { Authorization: `Bearer ${ctx.accessToken}`, "X-Org-Id": ctx.orgId },
        data,
      });
    },
    async get(path: string) {
      return request.get(`${API_URL}${path}`, {
        headers: { Authorization: `Bearer ${ctx.accessToken}`, "X-Org-Id": ctx.orgId },
      });
    },
  };
}

// ── MailHog (SMTP sink) ─────────────────────────────────────────────────────

export const MAILHOG_API_URL = process.env.MAILHOG_API_URL ?? "http://localhost:8025";

export interface MailhogMessage {
  to: string;
  subject: string;
  /** Raw MIME source — attachment assertions parse this. */
  raw: string;
}

/** All messages currently captured by MailHog. */
export async function mailhogMessages(
  request: APIRequestContext,
): Promise<MailhogMessage[]> {
  const res = await request.get(`${MAILHOG_API_URL}/api/v2/messages?limit=50`);
  if (!res.ok()) return [];
  const body = (await res.json()) as {
    items?: { To?: { Mailbox?: string; Domain?: string }[]; Content?: { Headers?: { Subject?: string[] }; Body?: string } }[];
  };
  return (body.items ?? []).map((item) => ({
    to: (item.To ?? []).map((t) => `${t.Mailbox}@${t.Domain}`).join(","),
    subject: item.Content?.Headers?.Subject?.[0] ?? "",
    raw: item.Content?.Body ?? "",
  }));
}

/**
 * The base64 body of the first `application/pdf` MIME part, or null.
 *
 * Deliberately tolerant of how the part is spelled: Python's EmailMessage
 * writes `Content-Type: application/pdf` + a quoted `filename=` + a per-part
 * `MIME-Version`, nodemailer writes `application/pdf; name=…` and no
 * `MIME-Version`, JavaMail folds long headers. The contract is "a PDF is
 * attached", not one library's serialisation — the ports must pass this too.
 */
export function pdfAttachmentBase64(raw: string): string | null {
  const flat = raw.replace(/\r\n/g, "\n");
  for (const part of flat.split(/\n--[^\n]+\n/)) {
    const sep = part.indexOf("\n\n");
    if (sep === -1) continue;
    const headers = part.slice(0, sep).replace(/\n[ \t]+/g, " "); // unfold
    if (!/content-type:\s*application\/pdf/i.test(headers)) continue;
    if (!/content-transfer-encoding:\s*base64/i.test(headers)) continue;
    const body = part.slice(sep + 2).split(/\n--/)[0]; // stop at the next boundary
    return body.replace(/\s+/g, "");
  }
  return null;
}

/** The reset token in a password-reset email (the console's `/reset-password?reset=…` link). */
export function resetTokenFromEmail(raw: string): string | null {
  // The body is quoted-printable: soft line breaks (`=\n`) split the long link
  // and `=` itself is spelled `=3D`. Decode before matching.
  const decoded = raw
    .replace(/=\r?\n/g, "")
    .replace(/=([0-9A-F]{2})/gi, (_, hex: string) => String.fromCharCode(parseInt(hex, 16)));
  return decoded.match(/\/reset-password\?reset=([A-Za-z0-9_-]+)/)?.[1] ?? null;
}

/** Poll until a message matching `predicate` lands (worker dispatch is async). */
export async function waitForEmail(
  request: APIRequestContext,
  predicate: (m: MailhogMessage) => boolean,
  timeoutMs = 15_000,
): Promise<MailhogMessage> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const found = (await mailhogMessages(request)).find(predicate);
    if (found) return found;
    if (Date.now() > deadline) {
      const all = await mailhogMessages(request);
      throw new Error(
        `expected email not received within ${timeoutMs}ms; mailbox: ${JSON.stringify(
          all.map((m) => ({ to: m.to, subject: m.subject })),
        )}`,
      );
    }
    await new Promise((r) => setTimeout(r, 500));
  }
}

// Re-export so journeys import one module.
export { base as test, expect };

// ── Platform operator ───────────────────────────────────────────────────────
// Grants and money movements are operator actions. The e2e stack seeds a
// platform admin (`synapse-cli seed --dev`); journeys that need an operator
// log in as that user. Credentials are the documented dev-seed defaults.

export const PLATFORM_ADMIN_EMAIL = process.env.E2E_PLATFORM_ADMIN_EMAIL ?? "owner@acme.example.com";
export const PLATFORM_ADMIN_PASSWORD = process.env.E2E_PLATFORM_ADMIN_PASSWORD ?? "password123";

export async function platformApi(request: APIRequestContext) {
  const login = await request.post(`${API_URL}/v1/auth/login`, {
    data: { email: PLATFORM_ADMIN_EMAIL, password: PLATFORM_ADMIN_PASSWORD },
  });
  const body = (await login.json().catch(() => ({}))) as { tokens?: { access_token: string } };
  expect(
    login.ok() && body.tokens?.access_token,
    `platform admin login: ${login.status()} — run synapse-cli seed --dev`,
  ).toBeTruthy();
  const headers = { Authorization: `Bearer ${body.tokens!.access_token}` };
  return {
    async post(path: string, data: unknown) {
      return request.post(`${API_URL}${path}`, { headers, data });
    },
    async get(path: string) {
      return request.get(`${API_URL}${path}`, { headers });
    },
    async delete(path: string) {
      return request.delete(`${API_URL}${path}`, { headers });
    },
  };
}
