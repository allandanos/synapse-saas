import {
  test,
  expect,
  createStackContext,
  loginConsole,
  api,
  emailFor,
  API_URL,
} from "./fixtures";

test.describe("platform journeys", () => {
  test("api key create → reveal once → revoke", async ({ page, request }) => {
    const ctx = await createStackContext(request, "apikeys");
    await loginConsole(page, ctx);

    await page.goto("/dashboard/api-keys");
    await page.getByPlaceholder(/CI pipeline/i).fill("e2e key");
    await page.getByRole("button", { name: /create key/i }).click();

    // Plaintext shown exactly once (the amber reveal box, not the copy snippet)
    const secret = page.locator("code", { hasText: /^sk_/ }).first();
    await expect(secret).toBeVisible();
    const secretValue = await secret.textContent();
    expect(secretValue).toMatch(/^sk_[A-Za-z0-9_-]{20,}$/);

    // Dismiss; the list shows the prefix only, never the full key again
    await page.getByRole("button", { name: /i'?ve saved it/i }).click();
    await expect(secret).toHaveCount(0);
    await expect(page.getByText(`${secretValue?.slice(0, 8)}…`).first()).toBeVisible();

    // Revoke kills the credential server-side
    const revoke = page.getByRole("button", { name: "Revoke" }).first();
    await revoke.click();
    await expect(page.getByText("revoked").first()).toBeVisible();

    const probe = await request.get(`${API_URL}/v1/entitlements`, {
      headers: { Authorization: `Bearer ${secretValue}` },
    });
    expect(probe.status()).toBe(401);
  });

  test("org switching is a hard tenant boundary in the UI", async ({
    page,
    request,
  }) => {
    const ctxA = await createStackContext(request, "switch-a");
    const ctxB = await createStackContext(request, "switch-b");

    // B upgrades; the invoice exists for B only
    await api(request, ctxB).post("/v1/subscription/change", { plan_key: "starter" });

    await loginConsole(page, ctxA);
    await page.goto("/dashboard/billing");
    await expect(page.getByText(/free/i).first()).toBeVisible();
    await expect(
      page.getByRole("table").getByText(/499/),
      "org A must not see org B's invoice",
    ).toHaveCount(0);

    // Members: A sees exactly its own owner row
    await page.goto("/dashboard/members");
    const rows = page.getByRole("table").getByRole("row");
    await expect(rows).toHaveCount(2); // header + owner
  });

  test("audit timeline records the journeys we just took", async ({ page, request }) => {
    const ctx = await createStackContext(request, "audit");
    const client = api(request, ctx);

    // Generate some audited activity
    await client.post("/v1/orgs/current/members/invite", { email: emailFor("aud") });
    await client.post("/v1/subscription/change", { plan_key: "starter" });

    await loginConsole(page, ctx);
    await page.goto("/dashboard/audit");
    await expect(page.getByText("member.invited")).toBeVisible();
    await expect(page.getByText("subscription.plan_changed")).toBeVisible();
  });

  test("feature flag checker on the developer portal", async ({ page, request }) => {
    const ctx = await createStackContext(request, "devportal");
    await loginConsole(page, ctx);

    await page.goto("/dashboard/developer");
    await page.getByPlaceholder(/new-editor/i).fill("new-editor");
    await page.getByRole("button", { name: "Check" }).click();
    // Unknown flags resolve disabled — dark by default
    await expect(page.getByText("disabled").first()).toBeVisible();
  });

  test("webhook endpoints: create → secret once → list", async ({ page, request }) => {
    const ctx = await createStackContext(request, "hooks");
    await loginConsole(page, ctx);

    await page.goto("/dashboard/webhooks");
    await page
      .getByPlaceholder(/example.com\/hooks/i)
      .fill("https://example.test/hooks/e2e");
    await page.getByRole("button", { name: /add endpoint/i }).click();

    const secret = page.getByText(/^whsec_/);
    await expect(secret).toBeVisible();
    await page.getByRole("button", { name: /i'?ve saved it/i }).click();

    await expect(page.getByText("https://example.test/hooks/e2e")).toBeVisible();
  });
});
