import { test } from "@playwright/test";
test("debug: log what useSearchParams returns after hydration", async ({ page }) => {
  await page.goto("/login?reset=done", { waitUntil: "networkidle" });
  await page.waitForTimeout(2500);
  // Wait for React to flush by interacting: click Sign In with empty fields
  // (triggers state update + re-render of LoginForm).
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForTimeout(800);
  const count = await page.getByText(/password updated/i).count();
  console.log("banner after interaction:", count);
  const email = await page.getByLabel("Email").inputValue().catch(() => "n/a");
  console.log("email still readable:", email);
});
