/**
 * White-label surface: the console renders the deployment's branding, which it
 * reads from the API at runtime (no rebuild). Runs against whatever branding
 * the stack's API serves — expectations come from /v1/branding itself, so the
 * spec holds for the default kit and for a custom SYNAPSE_BRANDING_FILE alike.
 */
import { test, expect, API_URL } from "./fixtures";

interface BrandingRead {
  name: string;
  tagline: string | null;
  assets: { logo: string | null; favicon: string | null };
  colors: { primary: string };
  landing: "page" | "redirect";
  powered_by: boolean;
}

async function fetchBranding(request: import("@playwright/test").APIRequestContext) {
  const res = await request.get(`${API_URL}/v1/branding`);
  expect(res.status(), "GET /v1/branding").toBe(200);
  return (await res.json()) as BrandingRead;
}

test.describe("branding", () => {
  test("API serves the branding JSON", async ({ request }) => {
    const brand = await fetchBranding(request);
    expect(brand.name.length).toBeGreaterThan(0);
    expect(brand.colors.primary).toMatch(/^#[0-9a-fA-F]{6}$/);
  });

  test("login page carries the brand: name, favicon, logo, colour tokens", async ({
    page,
    request,
  }) => {
    const brand = await fetchBranding(request);
    await page.goto("/login");

    await expect(page.getByText(brand.name, { exact: true }).first()).toBeVisible();

    if (brand.assets.favicon) {
      const href = await page.locator('link[rel="icon"]').first().getAttribute("href");
      expect(href, "favicon is loaded from the public API URL").toMatch(
        new RegExp(`^${API_URL.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/v1/branding/assets/`),
      );
    }

    if (brand.assets.logo) {
      const logo = page.locator('img[src*="/v1/branding/assets/"]').first();
      await expect(logo).toBeVisible();
      await expect
        .poll(() => logo.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth))
        .toBeGreaterThan(0);
    }

    const primary = await page.evaluate(() =>
      document.documentElement.style.getPropertyValue("--brand-primary"),
    );
    expect(primary).toBe(brand.colors.primary);
  });

  test("landing page shows name, tagline, both ways in and the footer", async ({
    page,
    request,
  }) => {
    const brand = await fetchBranding(request);
    test.skip(brand.landing === "redirect", "deployment sends / straight to /login");

    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1, name: brand.name })).toBeVisible();
    if (brand.tagline) await expect(page.getByText(brand.tagline)).toBeVisible();

    await expect(page.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
    await expect(page.getByRole("link", { name: "Create account" })).toHaveAttribute(
      "href",
      "/register",
    );

    const poweredBy = page.getByRole("link", { name: "Powered by Synapse" });
    if (brand.powered_by) await expect(poweredBy).toBeVisible();
    else await expect(poweredBy).toHaveCount(0);

    expect(
      await page.evaluate(() => document.documentElement.style.getPropertyValue("--brand-primary")),
    ).toBe(brand.colors.primary);
  });
});
