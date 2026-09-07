/**
 * Agent governance journeys — the Phase 4 surface (ADR 0007):
 * the paywall, the registry lifecycle in the console, and AI metering
 * moving the console's usage meters.
 */
import { test, expect, createStackContext, loginConsole, api, API_URL } from "./fixtures";

test.describe("agents", () => {
  test("free org hits the upgrade wall, pro unblocks the registry", async ({
    page,
    request,
  }) => {
    const ctx = await createStackContext(request, "agentswall");
    await loginConsole(page, ctx);

    await page.goto("/dashboard/agents");
    await expect(page.getByRole("heading", { name: "AI Agents is a Pro feature" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Upgrade plan" })).toHaveAttribute(
      "href",
      "/dashboard/billing",
    );

    // Upgrade through the billing page's real flow (manual provider)
    await page.getByRole("link", { name: "Upgrade plan" }).click();
    const proCard = page.locator("section[aria-label='Plans'] > div", {
      hasText: "Pro",
    });
    await proCard.getByRole("button", { name: "Switch plan" }).click();
    await expect(page.getByText(/Activated pro/i)).toBeVisible();

    // The registry now renders its empty state
    await page.goto("/dashboard/agents");
    await expect(page.getByText("No agents registered yet.")).toBeVisible();
  });

  test("register → list → disable → enable through the console", async ({ page, request }) => {
    const ctx = await createStackContext(request, "agentscrud");
    const client = api(request, ctx);

    // Pro via API (checkout flow is covered above; here we test the registry UI)
    await client.post("/v1/billing/checkout", { plan_key: "pro" });
    await client.post("/v1/billing/checkout/confirm", { plan_key: "pro" });

    await loginConsole(page, ctx);
    await page.goto("/dashboard/agents");

    await page.getByLabel("Slug", { exact: true }).fill("support-bot");
    await page.getByLabel("Name", { exact: true }).fill("Support Bot");
    await page
      .getByLabel(/Config \(JSON/)
      .fill('{\n  "model": "gpt-4o-mini",\n  "tools": ["kb_search"]\n}');
    await page.getByRole("button", { name: "Register" }).click();

    await expect(page.getByText("support-bot")).toBeVisible();
    await expect(page.getByText("Support Bot").first()).toBeVisible();

    // Invalid JSON is caught client-side, message surfaced
    await page.getByLabel("Slug", { exact: true }).fill("another-bot");
    await page.getByLabel("Name", { exact: true }).fill("Another");
    await page.getByLabel(/Config \(JSON/).fill("{not json");
    await page.getByRole("button", { name: "Register" }).click();
    await expect(page.getByText("Config must be valid JSON")).toBeVisible();

    // Disable → status pill flips; enable → back
    await page.getByRole("button", { name: "Disable" }).click();
    await expect(page.locator("tr", { hasText: "support-bot" }).getByText("disabled")).toBeVisible();
    await page.getByRole("button", { name: "Enable" }).click();
    await expect(page.locator("tr", { hasText: "support-bot" }).getByText("active")).toBeVisible();
  });

  test("metered agent usage moves the console meters", async ({ page, request }) => {
    const ctx = await createStackContext(request, "agentsmeter");
    const client = api(request, ctx);
    await client.post("/v1/billing/checkout", { plan_key: "pro" });
    await client.post("/v1/billing/checkout/confirm", { plan_key: "pro" });

    // The runtime integration shape: execution actuals metered after the run
    const metered = await client.post("/v1/usage/events", {
      events: [
        { metric: "agent_executions", quantity: 7 },
        { metric: "ai_tokens", quantity: 125_000 },
        { metric: "tool_calls", quantity: 40 },
      ],
    });
    expect(metered.ok()).toBeTruthy();

    await loginConsole(page, ctx);
    await page.goto("/dashboard/usage");
    // Meters render metric keys with underscores → spaces, plus used/limit text
    await expect(page.getByText("agent executions")).toBeVisible();
    await expect(page.getByText(/7 \/ 10,000/)).toBeVisible();
  });
});
