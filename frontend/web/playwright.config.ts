import { defineConfig, devices } from "@playwright/test";

/**
 * Real-stack browser smoke. Defaults to the local compose React SPA.
 * Required CI sets OPENFDD_PLAYWRIGHT_REQUIRE_STACK=1 after starting a
 * disposable compose stack. Those tests run with retries 0. A skip or a
 * retry-pass fails the job.
 * Network mocks are banned in this suite.
 */
const baseURL = process.env.OPENFDD_PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:3000";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.OPENFDD_PLAYWRIGHT_REQUIRE_STACK === "1" ? 0 : process.env.CI ? 1 : 0,
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
