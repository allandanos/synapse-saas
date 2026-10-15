/**
 * Deployment-defined tour steps: `branding.yaml` `tour:` (served on
 * GET /v1/branding) adds steps, hides built-ins and gates them by role,
 * merged into the console's welcome tour by components/tour/steps.tsx.
 *
 * Needs the fixture kit: run the API (and worker) with
 *   SYNAPSE_BRANDING_FILE=apps/web/e2e/branding-kit/branding.yaml
 * Its two steps are developer-only and it hides Agents, so tour.spec.ts
 * (owner / member / mobile owner) is unaffected. Self-skips against a stack
 * serving no tour steps (ports, implementing apps, the default kit).
 */
import {
  test,
  expect,
  API_URL,
  createStackContext,
  joinOrg,
  loginConsole,
  plantSession,
  walkTour,
} from "./fixtures";

const KIT_HINT = "needs SYNAPSE_BRANDING_FILE=apps/web/e2e/branding-kit/branding.yaml";
const CUSTOM_STEP = "Enroll your API key";
const DEVELOPER_TITLES = [
  "Your organization",
  "Usage this period",
  "Enabled features",
  "API keys",
  CUSTOM_STEP,
  "Developer",
  "Webhooks",
  "Before you go",
  "That's it",
];
const OWNER_STEPS = 10;

interface BrandingTour {
  tour?: { steps?: { id: string }[] };
}

// The card animates between targets; reduced motion makes each step land at once.
test.use({ contextOptions: { reducedMotion: "reduce" } });

test.describe("deployment tour steps", () => {
  test.beforeAll(async () => {
    const res = await fetch(`${API_URL}/v1/branding`);
    expect(res.ok, `GET /v1/branding: ${res.status}`).toBeTruthy();
    const body = (await res.json()) as BrandingTour;
    test.skip((body.tour?.steps ?? []).length === 0, KIT_HINT);
  });

  test("a developer walks the injected steps, with the call to action", async ({
    page,
    request,
  }) => {
    const { joiner, orgId } = await joinOrg(request, "tour-config-dev", ["developer"]);
    await plantSession(page, { refreshToken: joiner.refreshToken, orgId }, "/dashboard");
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

    await page.getByRole("button", { name: "Take the tour" }).click();
    const titles = await walkTour(page, DEVELOPER_TITLES.length + 1, async (title, dialog) => {
      if (title !== CUSTOM_STEP) return;
      const link = dialog.getByRole("link", { name: "Open Acme" });
      await expect(link).toHaveAttribute("href", "https://example.com/acme");
      await expect(link).toHaveAttribute("target", "_blank");
    });
    expect(titles[0]).toMatch(/^Welcome to /);
    expect(titles.slice(1)).toEqual(DEVELOPER_TITLES);
    expect(titles).not.toContain("Agents"); // hidden by the kit
  });

  test("an owner's tour is unchanged by developer-only steps", async ({ page, request }) => {
    const ctx = await createStackContext(request, "tour-config-owner");
    await loginConsole(page, ctx);

    await page.getByRole("button", { name: "Take the tour" }).click();
    const titles = await walkTour(page, OWNER_STEPS);
    expect(titles).not.toContain(CUSTOM_STEP);
    expect(titles).not.toContain("Before you go");
    expect(titles.at(-1)).toBe("That's it");
  });

  test.describe("on a phone", () => {
    test.use({ viewport: { width: 390, height: 844 } });

    test("a menu-anchored step becomes a centred card", async ({ page, request }) => {
      const { joiner, orgId } = await joinOrg(request, "tour-config-phone", ["developer"]);
      await plantSession(page, { refreshToken: joiner.refreshToken, orgId }, "/dashboard");
      await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

      await page.getByRole("button", { name: "Open menu" }).click();
      await page.getByRole("button", { name: "Take the tour" }).click();
      await expect(page.getByRole("button", { name: "Open menu" })).toBeVisible(); // menu closed

      const titles = await walkTour(page, 6);
      expect(titles.slice(1)).toEqual([
        "Usage this period",
        "Enabled features",
        CUSTOM_STEP,
        "Before you go",
        "That's it",
      ]);
    });
  });
});
