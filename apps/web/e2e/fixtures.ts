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
  expect(reg.ok(), `register ${email}`).toBeTruthy();
  const tokens = (await reg.json()).tokens as { access_token: string; refresh_token: string };

  const org = await request.post(`${API_URL}/v1/orgs`, {
    headers: { Authorization: `Bearer ${tokens.access_token}` },
    data: { name: `E2E ${label} Org` },
  });
  expect(org.ok(), "create org").toBeTruthy();
  const orgBody = (await org.json()) as { id: string; slug: string };

  return {
    accessToken: tokens.access_token,
    refreshToken: tokens.refresh_token,
    orgId: orgBody.id,
    orgSlug: orgBody.slug,
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

// Re-export so journeys import one module.
export { base as test, expect };
