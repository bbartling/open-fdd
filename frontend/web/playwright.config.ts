import { defineConfig, devices } from "@playwright/test";

/**
 * P1-M2-A: real-stack browser smoke. Defaults to local compose react SPA.
 * Skip automatically when OPENFDD_PLAYWRIGHT_SKIP=1 or base URL is unreachable
 * (CI without a live stack). Network mocks are banned in this suite.
 */
const baseURL = process.env.OPENFDD_PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:3000";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL,
    trace: "on-first-retry",
    video: "retain-on-failure",
    screenshot: "only-on-failure",
    ...devices["Desktop Chrome"],
    viewport: { width: 1280, height: 800 },
  },
  timeout: 60_000,
});
