import {
  test,
  expect,
  createStackContext,
  loginConsole,
  api,
  emailFor,
  API_URL,
} from "./fixtures";

test.describe("money path (manual provider — the whole loop runs locally)", () => {
  test("seat quota wall: invite until the free plan says stop, upgrade unblocks", async ({
    page,
    request,
  }) => {
    const ctx = await createStackContext(request, "quota");
    const client = api(request, ctx);
    await loginConsole(page, ctx);

    await page.goto("/dashboard/members");

    // Free plan = 3 seats (1 owner). Two invites pass…
    for (let i = 1; i <= 2; i++) {
      await page.getByPlaceholder(/teammate@example.com/).fill(emailFor(`seat${i}`));
      await page.getByRole("button", { name: "Invite" }).click();
      await expect(page.getByText(emailFor(`seat${i}`))).toBeVisible();
    }

    // …the third trips the 402 with upgrade hints
    await page.getByPlaceholder(/teammate@example.com/).fill(emailFor("seat3"));
    await page.getByRole("button", { name: "Invite" }).click();
    await expect(page.getByText(/seat limit reached|limit reached/i).first()).toBeVisible();

    // Upgrade to Starter (manual confirm — instant) and the invite passes
    await page.goto("/dashboard/billing");
    await switchToStarter(page);

    await page.goto("/dashboard/members");
    await page.getByPlaceholder(/teammate@example.com/).fill(emailFor("seat3"));
    await page.getByRole("button", { name: "Invite" }).click();
    await expect(page.getByText(emailFor("seat3"))).toBeVisible();
  });

  test("plan change issues an invoice the console lists", async ({ page, request }) => {
    const ctx = await createStackContext(request, "invoice");
    const client = api(request, ctx);
    await loginConsole(page, ctx);

    await page.goto("/dashboard/billing");
    await switchToStarter(page);

    // Manual provider records the invoice on confirmation
    await expect(
      page.getByRole("table").getByText(/499/).first(),
      "starter invoice row",
    ).toBeVisible();
  });

  test("trial grant flips a gated feature without a plan change", async ({
    page,
    request,
  }) => {
    const ctx = await createStackContext(request, "trial");
    const client = api(request, ctx);
    await loginConsole(page, ctx);

    await page.goto("/dashboard");
    await expect(page.getByText(/not on your current plan/i).first()).toBeVisible();

    // Grant advanced_reports as a 14-day promo (what an admin/console does)
    const grant = await client.post("/v1/entitlements/grants", {
      feature_key: "advanced_reports",
      source: "promo",
      duration_days: 14,
    });
    expect(grant.ok()).toBeTruthy();

    await page.reload();
    await expect(page.getByText(/advanced reports/i).first()).toBeVisible();
    await expect(page.getByText(/not on your current plan/i)).toHaveCount(0);
  });

  test("usage meters reflect consumed quota", async ({ page, request }) => {
    const ctx = await createStackContext(request, "usage");
    const client = api(request, ctx);

    const consume = await client.post("/v1/usage/consume", {
      events: [{ metric: "api_requests", quantity: 4242 }],
    });
    expect(consume.ok()).toBeTruthy();

    await loginConsole(page, ctx);
    await page.goto("/dashboard/usage");
    await expect(page.getByText("4,242").first()).toBeVisible();
    await expect(page.getByText(/10,000/).first()).toBeVisible(); // free-plan cap
  });

  test("billing invoices endpoint stays tenant-scoped", async ({ page, request }) => {
    const ctxA = await createStackContext(request, "invA");
    const ctxB = await createStackContext(request, "invB");

    // A upgrades (invoice created); B must never see it
    const upgrade = await api(request, ctxA).post("/v1/subscription/change", {
      plan_key: "starter",
    });
    expect(upgrade.ok()).toBeTruthy();

    const bInvoices = await api(request, ctxB).get("/v1/billing/invoices");
    expect(bInvoices.ok()).toBeTruthy();
    const body = (await bInvoices.json()) as unknown[];
    expect(body, "org B sees zero invoices").toHaveLength(0);
  });
});


/** The Starter plan card's switch button — scope to the card that CONTAINS
 * the heading (ancestor traversal), not every div nesting it. */
async function switchToStarter(page: import("@playwright/test").Page): Promise<void> {
  await page
    .locator("div.rounded-xl.border")
    .filter({ has: page.getByRole("heading", { name: "Starter", exact: true }) })
    .getByRole("button", { name: /switch plan/i })
    .click();
  await expect(page.getByText(/activated starter/i).first()).toBeVisible({ timeout: 15_000 });
}
