import { test, expect } from "@playwright/test";
import { ensureProductSession } from "./session";
import { failIfRequired, stackRequired } from "./requireStack";

const base = process.env.OPENFDD_PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:3000";

/**
 * T1284-5 — display preference presentation (real stack when required).
 */
test.describe("T1284-5 display preference", () => {
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
    await ensureProductSession(page, request);
  });

  test("imperial vs metric unit radios persist in localStorage", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("auth-gate-loading")).toHaveCount(0, { timeout: 15_000 });
    const imperialRadio = page.getByRole("radio", { name: /imperial/i });
    const metricRadio = page.getByRole("radio", { name: /metric|si/i });
    if ((await imperialRadio.count()) === 0) {
      test.skip(true, "Units radios not visible on this view");
      return;
    }
    await metricRadio.check();
    await expect
      .poll(async () =>
        page.evaluate(() => localStorage.getItem("openfdd.ui.display_units")),
      )
      .toBe("metric");
    await imperialRadio.check();
    await expect
      .poll(async () =>
        page.evaluate(() => localStorage.getItem("openfdd.ui.display_units")),
      )
      .toBe("imperial");
  });
});
