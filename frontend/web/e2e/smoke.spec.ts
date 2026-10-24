import { test, expect } from "@playwright/test";
import { failIfRequired, stackRequired } from "./requireStack";
import { ensureProductSession } from "./session";

/**
 * Real-stack smoke — no route/network mocks. Requires react SPA on :3000
 * and central reachable via same-origin /api (or proxied).
 */
test.describe("react product smoke (real stack)", () => {
  test.beforeAll(async ({ request }) => {
    if (process.env.OPENFDD_PLAYWRIGHT_SKIP === "1") {
      failIfRequired("OPENFDD_PLAYWRIGHT_SKIP=1");
    }
    const base = process.env.OPENFDD_PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:3000";
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

  test("SPA shell loads without console errors", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(String(err)));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });

    await page.goto("/");
    await expect(page.locator("#root")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("overview-page")).toBeVisible({ timeout: 15_000 });

    expect(errors, `console/page errors: ${errors.join(" | ")}`).toEqual([]);
  });

  test("primary routes render shell", async ({ page }) => {
    for (const path of ["/auth", "/jobs", "/upload", "/rules", "/findings", "/reports"]) {
      await page.goto(path);
      await expect(page.locator("#root")).toBeVisible({ timeout: 15_000 });
    }
  });
});
