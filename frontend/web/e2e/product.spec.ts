import { test, expect } from "@playwright/test";
import { collectPageErrors, simulateLanHttpCrypto } from "./lanHttp";

/**
 * P1-M3 real-stack product markers — no route/network mocks.
 * Nightly gate 16 sets OPENFDD_PLAYWRIGHT_REQUIRE_STACK=1 so SPA-down is a hard fail.
 * CI without a stack may omit that env and soft-skip like smoke.spec.ts.
 */
const base = process.env.OPENFDD_PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:3000";
const requireStack = process.env.OPENFDD_PLAYWRIGHT_REQUIRE_STACK === "1";

test.describe("react product workflows (real stack)", () => {
  test.beforeAll(async ({ request }) => {
    if (process.env.OPENFDD_PLAYWRIGHT_SKIP === "1") {
      test.skip(true, "OPENFDD_PLAYWRIGHT_SKIP=1");
    }
    try {
      const res = await request.get(base, { timeout: 5_000 });
      if (!res.ok()) {
        if (requireStack) {
          throw new Error(`SPA not healthy at ${base} (HTTP ${res.status()})`);
        }
        test.skip(true, `SPA not healthy at ${base} (HTTP ${res.status()})`);
      }
    } catch (err) {
      if (requireStack) {
        throw err instanceof Error ? err : new Error(String(err));
      }
      test.skip(true, `SPA unreachable at ${base}`);
    }
  });

  test("overview loads capabilities and generation markers", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(String(err)));

    await page.goto("/");
    await expect(page.getByTestId("overview-page")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("home-loading")).toHaveCount(0, { timeout: 20_000 });
    await expect(page.getByTestId("overview-react-ui")).toContainText(/on|off|—/);
    await expect(page.getByTestId("overview-ui-generation")).toBeVisible();
    await expect(page.getByTestId("contract-version")).toBeVisible();
    expect(errors, `page errors: ${errors.join(" | ")}`).toEqual([]);
  });

  test("auth page login mints or refreshes session", async ({ page }) => {
    await page.goto("/auth");
    await expect(page.getByTestId("auth-page")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("auth-required")).toBeVisible();

    const password = process.env.OPENFDD_ADMIN_PASSWORD ?? "";
    await page.getByTestId("auth-username").fill("admin");
    if (password) {
      await page.getByTestId("auth-password").fill(password);
    }
    await page.getByTestId("auth-login").click();
    await expect(page.getByTestId("auth-notice")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("auth-notice")).toContainText(/Logged in/i);
  });

  test("auth login works without crypto.randomUUID (LAN HTTP)", async ({ page }) => {
    // Loopback Playwright is a secure context — strip randomUUID so we catch
    // the http://192.168.x.x failure mode that blanked remote login.
    await simulateLanHttpCrypto(page);
    const errors = collectPageErrors(page);

    await page.goto("/auth");
    await expect(page.getByTestId("auth-page")).toBeVisible({ timeout: 15_000 });

    const hasUuid = await page.evaluate(
      () => typeof globalThis.crypto?.randomUUID === "function",
    );
    expect(hasUuid, "simulateLanHttpCrypto must remove randomUUID").toBe(false);

    const password = process.env.OPENFDD_ADMIN_PASSWORD ?? "";
    await page.getByTestId("auth-username").fill("admin");
    if (password) {
      await page.getByTestId("auth-password").fill(password);
    }
    await page.getByTestId("auth-login").click();
    await expect(page.getByTestId("auth-notice")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("auth-notice")).toContainText(/Logged in/i);

    const uuidErrors = errors.filter((e) => /randomUUID/i.test(e));
    expect(uuidErrors, `LAN crypto errors: ${uuidErrors.join(" | ")}`).toEqual([]);
  });

  test("/login bookmark is not a blank page (redirects to /auth)", async ({ page }) => {
    // Regression: SPA had no /login route → empty #root for remote bookmarks.
    const errors = collectPageErrors(page);
    const response = await page.goto("/login", { waitUntil: "networkidle" });
    // nginx may 302 before SPA Navigate; either path must land on auth UI.
    const status = response?.status() ?? 0;
    expect([200, 302, 301]).toContain(status);
    await expect(page).toHaveURL(/\/auth\/?$/);
    await expect(page.getByTestId("auth-page")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("auth-username")).toBeVisible();
    await expect(page.getByTestId("auth-login")).toBeVisible();
    const rootHtml = await page.locator("#root").innerHTML();
    expect(rootHtml.length, "blank #root after /login").toBeGreaterThan(0);
    expect(
      errors.filter((e) => /randomUUID/i.test(e)),
      `page errors: ${errors.join(" | ")}`,
    ).toEqual([]);
  });

  test("jobs page shell and create section", async ({ page }) => {
    await page.goto("/jobs");
    await expect(page.getByTestId("jobs-page")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("jobs-create-section")).toBeVisible();
    await expect(page.getByTestId("jobs-create-name")).toBeVisible();
  });

  test("primary product routes expose page markers", async ({ page }) => {
    const routes: { path: string; testId: string }[] = [
      { path: "/upload", testId: "upload-page" },
      { path: "/mapping", testId: "mapping-page" },
      { path: "/rules", testId: "rules-page" },
      { path: "/findings", testId: "findings-page" },
      { path: "/reports", testId: "reports-page" },
      { path: "/metering", testId: "metering-page" },
      { path: "/wattlab", testId: "wattlab-page" },
      { path: "/twin", testId: "twin-page" },
    ];
    for (const { path, testId } of routes) {
      await page.goto(path);
      await expect(page.getByTestId(testId), `${path} → ${testId}`).toBeVisible({
        timeout: 15_000,
      });
    }
  });

  test("overview Plotly hosts expose named PNG stems when charts render", async ({
    page,
  }) => {
    await page.goto("/");
    await expect(page.getByTestId("overview-page")).toBeVisible({ timeout: 20_000 });
    const hosts = page.locator("[data-download-filename]");
    const n = await hosts.count();
    if (n === 0) {
      test.info().annotations.push({
        type: "note",
        description: "no Plotly hosts yet (empty site) — skip filename assert",
      });
      return;
    }
    for (let i = 0; i < n; i++) {
      const name = await hosts.nth(i).getAttribute("data-download-filename");
      expect(name, "download filename must be a non-empty stem").toBeTruthy();
      expect(name).not.toBe("newplot");
    }
  });
});
