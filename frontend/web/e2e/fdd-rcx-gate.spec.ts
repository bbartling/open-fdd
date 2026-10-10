import { test, expect } from "@playwright/test";
import { collectPageErrors } from "./lanHttp";
import { ensureProductSession } from "./session";

const buildingId = process.env.OPENFDD_GATE_BUILDING_ID ?? "";

test.describe("FDD / RCx gate (real stack)", () => {
  test.beforeEach(async ({ page, request }) => {
    await ensureProductSession(page, request);
  });

  test("Overview + Lab + FDD Plots + RCx without console storm", async ({ page }) => {
    test.skip(!buildingId, "OPENFDD_GATE_BUILDING_ID required");
    test.skip(!process.env.OPENFDD_ADMIN_PASSWORD, "OPENFDD_ADMIN_PASSWORD required");

    const errors = collectPageErrors(page);
    const q = `?site=${encodeURIComponent(buildingId)}`;

    await page.goto(`/${q}`);
    await expect(page.getByTestId("overview-page")).toBeVisible({ timeout: 25_000 });
    await expect(page.getByTestId("home-loading")).toHaveCount(0, { timeout: 25_000 });

    await page.goto(`/rules${q}`);
    await expect(page.getByTestId("overview-page")).toBeVisible({ timeout: 20_000 });

    await page.goto(`/reports?section=fdd-plots${q.replace("?", "&")}`);
    await expect(page.getByTestId("reports-page")).toBeVisible({ timeout: 20_000 });

    await page.goto(`/rcx${q}`);
    await expect(page.getByTestId("rcx-page")).toBeVisible({ timeout: 20_000 });
    const rcxErr = page.getByTestId("rcx-error");
    if (await rcxErr.isVisible().catch(() => false)) {
      const msg = (await rcxErr.textContent()) ?? "";
      expect(msg, "RCx must not show DataFusion planning errors").not.toMatch(
        /Utf8View|avg\(|planning|Internal error/i,
      );
    }

    const bad = errors.filter(
      (e) => !/favicon|ResizeObserver|Loading chunk/i.test(e),
    );
    expect(bad, `page errors: ${bad.join(" | ")}`).toEqual([]);
  });
});
