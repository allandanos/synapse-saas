import { test, expect, emailFor, createStackContext,
  resetTokenFromEmail,
  waitForEmail, API_URL } from "./fixtures";

test.describe("auth journeys", () => {
  test("register → onboarding → first dashboard", async ({ page }) => {
    const email = emailFor("register");
    await page.goto("/register");
    await page.getByLabel("Name").fill("E2E Register");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill("password12345");
    await page.getByRole("button", { name: /create account/i }).click();

    // Fresh user with no org lands on onboarding
    await page.waitForURL(/onboarding/);
    await expect(page.getByRole("heading", { name: /create your organization/i })).toBeVisible();

    await page.getByLabel(/organization name/i).fill("E2E First Org");
    await page.getByRole("button", { name: /create organization/i }).click();

    await page.waitForURL(/dashboard/);
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
    // Free-plan bootstrap visible: usage meters render
    await expect(page.getByText(/plan/i).first()).toBeVisible();
  });

  test("login shows post-reset banner via ?reset=done", async ({ page }) => {
    await page.goto("/login?reset=done");
    await expect(page.getByText(/password updated/i)).toBeVisible();
  });

  test("forgot-password is opaque for unknown emails", async ({ page }) => {
    await page.goto("/forgot-password");
    await page.getByLabel("Email").fill(`nobody-${Date.now()}@example.com`);
    await page.getByRole("button", { name: /send reset link/i }).click();
    // Same confirmation regardless of account existence
    await expect(page.getByText(/if an account exists/i)).toBeVisible();
  });

  test("password reset end-to-end via emailed token (outbox)", async ({
    page,
    request,
  }) => {
    const ctx = await createStackContext(request, "reset");

    // Trigger the reset through the API (the console page only links here)
    const forgot = await request.post(`${API_URL}/v1/auth/forgot-password`, {
      data: { email: ctx.email },
    });
    expect(forgot.status(), "forgot-password is an opaque 202").toBe(202);

    // The token rides the internal outbox → worker → SMTP: read it from MailHog
    // exactly as the user would, and follow the link the email contains.
    const mail = await waitForEmail(
      request,
      // The subject carries the product name ("Reset your <name> password").
      (m) => m.to === ctx.email && /^reset your .*password$/i.test(m.subject),
    );
    const token = resetTokenFromEmail(mail.raw);
    expect(token, "reset link with a token in the email").toBeTruthy();

    await page.goto(`/reset-password?reset=${token}`);
    await page.getByLabel(/new password/i).fill("new-password-123");
    await page.getByRole("button", { name: /set new password/i }).click();
    await page.waitForURL(/\/login\?reset=done/);
    await expect(page.getByText(/password updated/i)).toBeVisible();

    // The new password works, the old one does not
    const fresh = await request.post(`${API_URL}/v1/auth/login`, {
      data: { email: ctx.email, password: "new-password-123" },
    });
    expect(fresh.ok(), `login with the new password: ${fresh.status()}`).toBeTruthy();
    const stale = await request.post(`${API_URL}/v1/auth/login`, {
      data: { email: ctx.email, password: "password12345" },
    });
    expect(stale.status()).toBe(401);

    // A bogus token surfaces as a problem, not a crash
    await page.goto("/reset-password?reset=not-a-real-token");
    await page.getByLabel(/new password/i).fill("another-password-123");
    await page.getByRole("button", { name: /set new password/i }).click();
    await expect(page.locator("text=/invalid|expired|not found/i").first()).toBeVisible();
  });

  test("logout returns to login and clears the session", async ({ page, request }) => {
    const ctx = await createStackContext(request, "logout");
    await page.context().addCookies([
      { name: "synapse_rt", value: ctx.refreshToken, domain: "localhost", path: "/", httpOnly: true, sameSite: "Lax" },
      { name: "synapse_org", value: ctx.orgId, domain: "localhost", path: "/" },
    ]);
    await page.goto("/dashboard");
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

    await page.getByRole("button", { name: /sign out/i }).click();
    await page.waitForURL(/login/);
    // Navigating back does not resurrect the session
    await page.goto("/dashboard");
    await page.waitForURL(/login/);
  });
});
