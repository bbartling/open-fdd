import { test, expect } from "@playwright/test";
import { failIfRequired, stackRequired } from "./requireStack";
import { ensureProductSession } from "./session";

/**
 * T1130-1 — strict style-src CSP: zero securitypolicyviolation events on
 * product surfaces that host Plotly, with at least one SVG per chart host.
 */
const base = process.env.OPENFDD_PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:3000";

type CspViolation = {
  violatedDirective: string;
  blockedURI: string;
  sample: string;
};

test.describe("CSP style split + Plotly (real stack)", () => {
  test.beforeAll(async ({ request }) => {
    if (process.env.OPENFDD_PLAYWRIGHT_SKIP === "1") {
      failIfRequired("OPENFDD_PLAYWRIGHT_SKIP=1");
    }
    let res;
    try {
      res = await request.get(base, { timeout: 5_000 });
    } catch (err) {
      if (stackRequired) {
        throw err instanceof Error ? err : new Error(String(err));
      }
      test.skip(true, `SPA unreachable at ${base}`);
      return;
    }
    if (!res.ok()) {
      failIfRequired(`SPA not healthy at ${base} (HTTP ${res.status()})`);
    }
  });

  test.beforeEach(async ({ page, request }) => {
    await page.addInitScript(() => {
      const list: CspViolation[] = [];
      (window as unknown as { __cspViolations?: CspViolation[] }).__cspViolations =
        list;
      document.addEventListener("securitypolicyviolation", (e) => {
        list.push({
          violatedDirective: e.violatedDirective,
          blockedURI: e.blockedURI,
          sample: e.sample,
        });
      });
    });
    await ensureProductSession(page, request);
  });

  async function violations(page: import("@playwright/test").Page): Promise<CspViolation[]> {
    return page.evaluate(() => (window as unknown as { __cspViolations?: CspViolation[] }).__cspViolations ?? []);
  }

  async function assertPlotlyHostsDrawn(page: import("@playwright/test").Page) {
    const hosts = page.locator('[data-testid^="plotly-host-"]');
    const count = await hosts.count();
    expect(count, "expected at least one Plotly host").toBeGreaterThan(0);
    for (let i = 0; i < count; i += 1) {
      const host = hosts.nth(i);
      const div = host.locator('[data-testid^="plotly-div-"]');
      await expect(div).toBeVisible({ timeout: 60_000 });
      const svgCount = await div.locator("svg.main-svg").count();
      expect(svgCount, `Plotly host ${i} must render svg.main-svg`).toBeGreaterThan(0);
    }
  }

  test("Overview loads with zero CSP violations", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("overview-page")).toBeVisible({ timeout: 25_000 });
    await expect(page.getByTestId("home-loading")).toHaveCount(0, { timeout: 25_000 });
    expect(await violations(page)).toEqual([]);
  });

  test("RCx Plots — no CSP violations and Plotly SVG drawn", async ({ page }) => {
    await page.goto("/rcx");
    await expect(page.getByTestId("rcx-page")).toBeVisible({ timeout: 25_000 });
    await assertPlotlyHostsDrawn(page);
    expect(await violations(page)).toEqual([]);
  });

  test("Inspect — no CSP violations and Plotly SVG drawn", async ({ page }) => {
    await page.goto("/inspect");
    await expect(page.getByTestId("inspect-page")).toBeVisible({ timeout: 25_000 });
    await assertPlotlyHostsDrawn(page);
    expect(await violations(page)).toEqual([]);
  });

  test("FDD Plots — no CSP violations and Plotly SVG drawn", async ({ page }) => {
    await page.goto("/reports?section=fdd-plots");
    await expect(page.getByTestId("reports-page")).toBeVisible({ timeout: 25_000 });
    await assertPlotlyHostsDrawn(page);
    expect(await violations(page)).toEqual([]);
  });

  test("Actions — no CSP violations", async ({ page }) => {
    await page.goto("/actions");
    await expect(page.getByTestId("actions-page")).toBeVisible({ timeout: 25_000 });
    expect(await violations(page)).toEqual([]);
  });
});
