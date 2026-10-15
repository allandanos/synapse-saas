/**
 * Product tour (NextStep): auto-starts once after org creation, replays from
 * the shell footer, persists completed/skipped to `preferences.tours` via
 * PATCH /v1/auth/me, and filters its steps by role and viewport.
 *
 * Step counts come from components/tour/steps.tsx `buildTour`:
 * desktop owner/admin 10, member 4; mobile owner 5.
 */
import type { APIRequestContext, Page } from "@playwright/test";
import {
  test,
  expect,
  API_URL,
  api,
  createStackContext,
  inviteTokenFromEmail,
  loginConsole,
  me,
  plantSession,
  registerOnly,
  waitForEmail,
  type RegisteredUser,
} from "./fixtures";

const TOUR = "console-welcome";
const OWNER_STEPS = 10;

// The card animates between targets; reduced motion makes each step land at once.
test.use({ contextOptions: { reducedMotion: "reduce" } });

/** Settles one animation frame: auto-start schedules its start on requestAnimationFrame. */
async function settleFrame(page: Page) {
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
}

/** Polls the API until the tour record is persisted (the PATCH is fire-and-forget). */
async function expectTourStatus(
  request: APIRequestContext,
  accessToken: string,
  status: "completed" | "skipped",
) {
  await expect
    .poll(async () => (await me(request, accessToken)).preferences.tours?.[TOUR]?.status)
    .toBe(status);
  const record = (await me(request, accessToken)).preferences.tours?.[TOUR];
  expect(record?.version).toBe(1);
  expect(Number.isNaN(Date.parse(record?.at ?? ""))).toBe(false);
}

/** Invite a fresh user as `member` into `owner`'s org and accept via the API. */
async function joinAsMember(
  request: APIRequestContext,
  label: string,
): Promise<{ joiner: RegisteredUser; orgId: string }> {
  const owner = await createStackContext(request, `${label}-owner`);
  const joiner = await registerOnly(request, label);
  const sent = await api(request, owner).post("/v1/orgs/current/members/invite", {
    email: joiner.email,
  });
  expect(sent.ok(), `invite: ${sent.status()}`).toBeTruthy();

  const mail = await waitForEmail(
    request,
    (m) => m.to.split(",").includes(joiner.email) && /invited/i.test(m.subject),
  );
  const token = inviteTokenFromEmail(mail.raw);
  expect(token, `invite token in the email to ${joiner.email}`).toBeTruthy();

  const accepted = await request.post(`${API_URL}/v1/auth/accept-invite`, {
    headers: { Authorization: `Bearer ${joiner.accessToken}` },
    data: { token },
  });
  expect(accepted.ok(), `accept-invite: ${accepted.status()}`).toBeTruthy();
  return { joiner, orgId: owner.orgId };
}

function tourDialog(page: Page) {
  return page.getByRole("dialog");
}

/** Titles of every step, walking the tour with Next until Done. */
async function walkTour(page: Page, total: number): Promise<string[]> {
  const dialog = tourDialog(page);
  const titles: string[] = [];
  for (let i = 1; i <= total; i += 1) {
    await expect(dialog).toContainText(`Step ${i} of ${total}`);
    titles.push((await dialog.getByRole("heading", { level: 2 }).textContent()) ?? "");
    await dialog.getByRole("button", { name: i === total ? "Done" : "Next" }).click();
  }
  return titles;
}

test.describe("product tour", () => {
  test("auto-starts once after org creation; Escape skips and persists", async ({
    page,
    request,
  }) => {
    const user = await registerOnly(request, "tour-new");
    await plantSession(page, user, "/onboarding");
    await page.getByLabel(/organization name/i).fill("E2E Tour Org");
    await page.getByRole("button", { name: /create organization/i }).click();

    // ?welcome=1 is stripped before the tour starts.
    await expect(page).toHaveURL(/\/dashboard$/);
    const welcome = page.getByRole("dialog", { name: /welcome/i });
    await expect(welcome).toBeVisible();
    await expect(welcome).toContainText(`Step 1 of ${OWNER_STEPS}`);
    await expect(welcome.getByRole("button", { name: "Back" })).toHaveCount(0);

    await page.keyboard.press("Escape");
    await expect(tourDialog(page)).toHaveCount(0);
    await expectTourStatus(request, user.accessToken, "skipped");

    await page.reload();
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
    await settleFrame(page);
    await expect(tourDialog(page)).toHaveCount(0);

    // A replayed welcome link never re-offers a version already seen.
    await page.goto("/dashboard?welcome=1");
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
    await settleFrame(page);
    await expect(tourDialog(page)).toHaveCount(0);
  });

  test("footer button replays the tour; completion persists", async ({ page, request }) => {
    const ctx = await createStackContext(request, "tour-replay");
    await loginConsole(page, ctx);
    await expect(tourDialog(page)).toHaveCount(0);

    await page.getByRole("button", { name: "Take the tour" }).click();
    const dialog = tourDialog(page);
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Back" })).toHaveCount(0);
    await expect(dialog).toBeFocused();

    await dialog.getByRole("button", { name: "Next" }).click();
    await expect(dialog).toContainText(`Step 2 of ${OWNER_STEPS}`);
    await expect(dialog.getByRole("button", { name: "Back" })).toBeVisible();
    await dialog.getByRole("button", { name: "Back" }).click();

    const titles = await walkTour(page, OWNER_STEPS);
    expect(titles[0]).toMatch(/^Welcome to /);
    expect(titles).toContain("Members");
    expect(titles).not.toContain("Agents"); // developer-only step
    expect(titles.at(-1)).toBe("That's it");

    await expect(dialog).toHaveCount(0);
    await expectTourStatus(request, ctx.accessToken, "completed");
  });

  test("existing users are never auto-interrupted", async ({ page, request }) => {
    const ctx = await createStackContext(request, "tour-existing");
    await loginConsole(page, ctx);
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
    await settleFrame(page);
    await expect(tourDialog(page)).toHaveCount(0);
  });

  test("the joined banner offers the tour to invitees", async ({ page, request }) => {
    const { joiner, orgId } = await joinAsMember(request, "tour-invitee");
    await plantSession(page, { refreshToken: joiner.refreshToken, orgId }, `/dashboard?joined=${orgId}`);

    const banner = page.getByRole("status");
    await expect(banner).toHaveText(/You've joined/);
    await expect(tourDialog(page)).toHaveCount(0); // no auto-start on ?joined=

    await banner.getByRole("button", { name: "Take the tour" }).click();
    await expect(page.getByRole("dialog", { name: /welcome/i })).toBeVisible();
    await expect(page).toHaveURL(/\/dashboard$/);
  });

  test("a member sees the short tour", async ({ page, request }) => {
    const { joiner, orgId } = await joinAsMember(request, "tour-member");
    await plantSession(page, { refreshToken: joiner.refreshToken, orgId }, "/dashboard");
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

    await page.getByRole("button", { name: "Take the tour" }).click();
    const titles = await walkTour(page, 4);
    expect(titles.slice(1)).toEqual(["Your organization", "Enabled features", "That's it"]);
    expect(titles).not.toContain("Members");
    await expectTourStatus(request, joiner.accessToken, "completed");
  });

  test.describe("on a phone", () => {
    test.use({ viewport: { width: 390, height: 844 } });

    test("drops the steps whose anchors live in the collapsed menu", async ({ page, request }) => {
      const ctx = await createStackContext(request, "tour-mobile");
      await loginConsole(page, ctx);

      await page.getByRole("button", { name: "Open menu" }).click();
      await page.getByRole("button", { name: "Take the tour" }).click();
      await expect(page.getByRole("button", { name: "Open menu" })).toBeVisible(); // menu closed

      const titles = await walkTour(page, 5);
      expect(titles.slice(1)).toEqual([
        "Plan and status",
        "Usage this period",
        "Enabled features",
        "That's it",
      ]);
    });
  });
});
