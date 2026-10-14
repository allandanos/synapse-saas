/**
 * Join-by-invite: the emailed `/register?invite=` link names the org, a new
 * user registers straight into it, an existing user signs in via
 * `/login?invite=` and can switch between their orgs with the data following.
 */
import type { APIRequestContext, Browser, Page } from "@playwright/test";
import {
  test,
  expect,
  api,
  createStackContext,
  emailFor,
  inviteTokenFromEmail,
  loginConsole,
  usageMeter,
  waitForEmail,
} from "./fixtures";

const PASSWORD = "password12345";

async function inviteTokenFor(request: APIRequestContext, email: string): Promise<string> {
  const message = await waitForEmail(
    request,
    (m) => m.to.split(",").includes(email) && /invited/i.test(m.subject),
  );
  const token = inviteTokenFromEmail(message.raw);
  expect(token, `invite token in the email to ${email}`).toBeTruthy();
  return token!;
}

/** A fresh browser context: no cookies from the inviting owner's session. */
async function freshPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  return context.newPage();
}

test.describe("join by invite", () => {
  test("new user registers from the invite link into the invited org", async ({
    page,
    browser,
    request,
  }) => {
    const owner = await createStackContext(request, "invite");
    const inviteeEmail = emailFor("invitee");

    await loginConsole(page, owner);
    await page.goto("/dashboard/members");
    await page.getByPlaceholder(/teammate@example.com/).fill(inviteeEmail);
    await page.getByRole("button", { name: "Invite" }).click();
    await expect(page.getByText(inviteeEmail)).toBeVisible();

    const token = await inviteTokenFor(request, inviteeEmail);

    const invitee = await freshPage(browser);
    try {
      await invitee.goto(`/register?invite=${token}`);
      await expect(invitee.getByRole("heading", { name: "Join E2E invite Org" })).toBeVisible();
      await expect(invitee.getByText(/invited as member/i)).toBeVisible();
      await expect(invitee.getByLabel("Email")).toHaveValue(inviteeEmail);

      await invitee.getByLabel("Name").fill("E2E Invitee");
      await invitee.getByLabel("Password", { exact: true }).fill(PASSWORD);
      await invitee.getByRole("button", { name: /create account/i }).click();

      await expect(invitee).toHaveURL(/\/dashboard\?joined=/);
      await expect(invitee.getByRole("status")).toHaveText(/You've joined E2E invite Org/);
      await expect(invitee.locator("#org-switcher option:checked")).toHaveText("E2E invite Org");
      await expect(usageMeter(invitee, "users")).toContainText("2 / 3");

      await invitee.getByRole("button", { name: "Dismiss" }).click();
      await expect(invitee).toHaveURL(/\/dashboard$/);
      await expect(invitee.getByRole("status")).toHaveCount(0);
    } finally {
      await invitee.context().close();
    }
  });

  test("existing user accepts via sign-in and switches between orgs", async ({
    browser,
    request,
  }) => {
    const owner = await createStackContext(request, "invite2");
    const joiner = await createStackContext(request, "joiner");

    const sent = await api(request, owner).post("/v1/orgs/current/members/invite", {
      email: joiner.email,
      // developer carries member:read, so the joiner can list the invited org's members
      role_keys: ["developer"],
    });
    expect(sent.ok(), `invite: ${sent.status()}`).toBeTruthy();
    const token = await inviteTokenFor(request, joiner.email);

    const page = await freshPage(browser);
    try {
      await page.goto(`/login?invite=${token}`);
      await expect(
        page.getByText("Sign in to accept your invitation to E2E invite2 Org"),
      ).toBeVisible();
      await page.getByLabel("Email").fill(joiner.email);
      await page.getByLabel("Password").fill(PASSWORD);
      await page.getByRole("button", { name: "Sign in" }).click();

      await expect(page).toHaveURL(/\/dashboard\?joined=/);
      await expect(page.getByRole("status")).toHaveText(/You've joined E2E invite2 Org/);

      const switcher = page.locator("#org-switcher");
      await expect(switcher.locator("option")).toHaveCount(2);
      await expect(switcher.locator("option:checked")).toHaveText("E2E invite2 Org");
      await expect(usageMeter(page, "users")).toContainText("2 / 3");

      // Own org: just the joiner
      await switcher.selectOption({ label: "E2E joiner Org" });
      await expect(usageMeter(page, "users")).toContainText("1 / 3");
      await page.getByRole("link", { name: "Members", exact: true }).click();
      await expect(page).toHaveURL(/\/dashboard\/members$/);
      await expect(page.getByRole("row").filter({ hasText: joiner.email })).toHaveCount(1);
      await expect(page.getByRole("row")).toHaveCount(2); // header + joiner

      // Invited org: owner + joiner — the members list re-queries on switch
      await switcher.selectOption({ label: "E2E invite2 Org" });
      await expect(page.getByRole("row").filter({ hasText: owner.email })).toHaveCount(1);
      await expect(page.getByRole("row")).toHaveCount(3); // header + owner + joiner
      await page.getByRole("link", { name: "Dashboard", exact: true }).click();
      await expect(usageMeter(page, "users")).toContainText("2 / 3");
    } finally {
      await page.context().close();
    }
  });
});
