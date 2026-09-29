/**
 * SSO journey against a REAL Keycloak (nightly `e2e-sso` job; locally:
 * docker compose --profile extras up -d keycloak and run the API with
 * SYNAPSE_IDENTITY_PROVIDER=keycloak). Skipped unless E2E_KEYCLOAK=1.
 */
import { test, expect } from "./fixtures";

const KEYCLOAK = process.env.E2E_KEYCLOAK === "1";

test.describe("single sign-on", () => {
  test.skip(!KEYCLOAK, "set E2E_KEYCLOAK=1 with a Keycloak-backed API");

  test("console offers SSO, Keycloak signs in, the session lands on the dashboard", async ({ page }) => {
    await page.goto("/login");
    await page.getByTestId("sso-button").click();

    // Keycloak's login form (realm import: sso@acme.example.com / password123)
    await page.waitForURL(/realms\/synapse\/protocol\/openid-connect\/auth/);
    await page.getByLabel(/username|email/i).fill("sso@acme.example.com");
    // By role + exact name: Keycloak ≥ 23 also renders a "Show password" toggle, so a
    // label regex on "password" resolves to two elements (strict-mode violation).
    await page.getByRole("textbox", { name: "Password", exact: true }).fill("password123");
    await page.getByRole("button", { name: /sign in/i }).click();

    // API callback → console /auth/callback → dashboard, or onboarding for a brand-new
    // user (the realm's sso@ user has no org: the dev seed does not create one for it)
    await page.waitForURL(/dashboard|onboarding/, { timeout: 20_000 });
    await expect(
      page.getByRole("heading", { name: /create your organization|dashboard|welcome/i }).first(),
    ).toBeVisible();
  });
});
