/**
 * Permission-aware console: the sidebar shows only the pages the viewer's
 * role can open (`orgs[].permission_keys` on GET /v1/auth/me), those pages
 * hide the controls the role cannot use, and a deep link to a gated page
 * lands on the "no access" panel — never on a red 403 alert.
 *
 * Alerts are asserted inside <main>: Next's route announcer is a
 * role="alert" node in an open shadow root that Playwright would also match.
 */
import type { Page } from "@playwright/test";
import { test, expect, joinOrg, me, plantSession } from "./fixtures";

const NO_ACCESS = "You don't have access to this page";

function navLink(page: Page, name: string) {
  return page.getByRole("navigation", { name: "Main" }).getByRole("link", { name, exact: true });
}

async function expectNav(page: Page, visible: string[], hidden: string[]) {
  for (const name of visible) await expect(navLink(page, name)).toBeVisible();
  for (const name of hidden) await expect(navLink(page, name)).toHaveCount(0);
}

function mainAlerts(page: Page) {
  return page.getByRole("main").getByRole("alert");
}

test.describe("permission-aware navigation", () => {
  test("a member sees only the pages their role can open", async ({ page, request }) => {
    const { owner, joiner, orgId } = await joinOrg(request, "perm-member");
    const membership = (await me(request, joiner.accessToken)).orgs.find((o) => o.id === orgId);
    expect(membership?.permission_keys).toContain("member:read");
    expect(membership?.permission_keys).not.toContain("billing:read");

    await plantSession(page, { refreshToken: joiner.refreshToken, orgId }, "/dashboard");
    await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
    await expectNav(
      page,
      ["Dashboard", "Members", "Usage", "Settings"],
      ["Agents", "Billing", "API keys", "Developer", "Audit log", "Webhooks"],
    );
    await expect(page.getByText("Plan details are visible to billing managers")).toBeVisible();
    await expect(mainAlerts(page)).toHaveCount(0);

    await navLink(page, "Members").click();
    await expect(page).toHaveURL(/\/dashboard\/members$/);
    await expect(page.getByRole("row").filter({ hasText: owner.email })).toHaveCount(1);
    await expect(page.getByRole("row").filter({ hasText: joiner.email })).toHaveCount(1);
    await expect(page.getByPlaceholder(/teammate/)).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Remove" })).toHaveCount(0);
    await expect(mainAlerts(page)).toHaveCount(0);

    await navLink(page, "Settings").click();
    await expect(page).toHaveURL(/\/dashboard\/settings$/);
    await expect(
      page.getByRole("main").getByText("E2E perm-member-owner Org", { exact: true }),
    ).toBeVisible();
    await expect(page.getByLabel("Organization name")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Save" })).toHaveCount(0);
  });

  test("deep links to a gated page show the no-access panel", async ({ page, request }) => {
    const { joiner, orgId } = await joinOrg(request, "perm-deeplink");
    await plantSession(page, { refreshToken: joiner.refreshToken, orgId }, "/dashboard/api-keys");

    await expect(page.getByRole("heading", { name: NO_ACCESS, level: 1 })).toBeVisible();
    await expect(page.getByRole("main")).toContainText("apikey:manage");
    await expect(page.getByRole("main")).toContainText("E2E perm-deeplink-owner Org");
    await expect(mainAlerts(page)).toHaveCount(0);
    await expect(navLink(page, "API keys")).toHaveCount(0);

    await page.getByRole("link", { name: "Back to dashboard" }).click();
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
    await expect(page.getByRole("heading", { name: NO_ACCESS })).toHaveCount(0);
  });

  test("a billing manager sees billing but not the org form", async ({ page, request }) => {
    const { joiner, orgId } = await joinOrg(request, "perm-billing", ["billing"]);
    await plantSession(page, { refreshToken: joiner.refreshToken, orgId }, "/dashboard");
    await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
    await expectNav(
      page,
      ["Dashboard", "Billing", "Usage", "Settings"],
      ["Members", "API keys", "Webhooks", "Audit log"],
    );

    await navLink(page, "Billing").click();
    await expect(page).toHaveURL(/\/dashboard\/billing$/);
    await expect(page.getByRole("region", { name: "Plans" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Switch plan" }).first()).toBeVisible();
    await expect(page.getByText("No billing contact set.")).toBeVisible();
    await expect(page.getByLabel("Billing contact email")).toHaveCount(0);
    await expect(mainAlerts(page)).toHaveCount(0);
  });
});
