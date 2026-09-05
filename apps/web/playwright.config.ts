import { defineConfig, devices } from "@playwright/test";

/**
 * E2E against the real stack — no mocks. Expects:
 *   docker compose up -d postgres redis   (or the full `docker compose up --build`)
 *   API on :8000, console on :3000 (pnpm build && pnpm start, or compose web)
 *
 * Video: recorded for EVERY test (watchable on pass too — that's the point),
 * plus traces and screenshots. Artifacts land in test-results/.
 *
 *   pnpm e2e           # headless, video for all
 *   pnpm e2e --headed   # watch live
 *   pnpm e2e --ui       # interactive
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false, // journeys share one org/user per file; sequential is honest
  retries: process.env.CI ? 1 : 0,
  workers: 1, // one org context at a time against a shared dev stack

  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],

  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    API_URL: process.env.E2E_API_URL ?? "http://localhost:8000",

    // Video for every test — watchable on green runs, evidence on red ones.
    video: "on",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",

    // Keep runs stable against the dev console's animation-friendly UI
    actionTimeout: 10_000,
    navigationTimeout: 20_000,
  },

  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
});
