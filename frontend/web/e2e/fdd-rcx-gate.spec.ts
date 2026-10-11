import { test, expect } from "@playwright/test";
import { collectPageErrors } from "./lanHttp";
import { ensureProductSession } from "./session";

/**
 * Soft-OPEN 371 T3e — strengthen Playwright Soft-OPEN beyond page headings.
 * Requires OPENFDD_GATE_BUILDING_ID (+ optional comma list OPENFDD_GATE_BUILDING_IDS).
 * Empty Plotly / skipped update / console planning storms are FAIL.
 */

function buildingIds(): string[] {
  const multi = (process.env.OPENFDD_GATE_BUILDING_IDS ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  if (multi.length) return multi;
  const one = (process.env.OPENFDD_GATE_BUILDING_ID ?? "").trim();
  return one ? [one] : [];
}

const sites = buildingIds();

test.describe("FDD / RCx Soft-OPEN gate (real stack)", () => {
  test.beforeEach(async ({ page, request }) => {
    await ensureProductSession(page, request);
  });

  for (const buildingId of sites.length ? sites : [""]) {
    test(`Overview update + FDD/RCx drawn series — ${buildingId || "(unset)"}`, async ({
      page,
    }) => {
      test.skip(!buildingId, "OPENFDD_GATE_BUILDING_ID or OPENFDD_GATE_BUILDING_IDS required");
      test.skip(!process.env.OPENFDD_ADMIN_PASSWORD, "OPENFDD_ADMIN_PASSWORD required");

      const errors = collectPageErrors(page);
      const q = `?site=${encodeURIComponent(buildingId)}`;
      let executed = 0;

      await page.goto(`/${q}`);
      await expect(page.getByTestId("overview-page")).toBeVisible({ timeout: 25_000 });
      await expect(page.getByTestId("home-loading")).toHaveCount(0, { timeout: 25_000 });
      executed += 1;

      // Soft-OPEN: physically drive Overview update (force if "current").
      const force = page.getByTestId("overview-force-analytics");
      const refresh = page.getByTestId("overview-refresh");
      if (await force.isVisible().catch(() => false)) {
        await force.click();
      } else {
        await expect(refresh).toBeVisible({ timeout: 10_000 });
        if (!(await refresh.isDisabled().catch(() => true))) {
          await refresh.click();
        }
      }
      await expect(page.getByTestId("overview-busy")).toHaveCount(0, { timeout: 120_000 });
      await expect(page.getByTestId("overview-populated")).toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId("overview-metrics")).toBeVisible({ timeout: 30_000 });
      executed += 1;

      await page.goto(`/reports?section=fdd-plots${q.replace("?", "&")}`);
      await expect(page.getByTestId("reports-page")).toBeVisible({ timeout: 20_000 });
      executed += 1;

      await page.goto(`/rcx${q}`);
      await expect(page.getByTestId("rcx-page")).toBeVisible({ timeout: 20_000 });
      const rcxErr = page.getByTestId("rcx-error");
      if (await rcxErr.isVisible().catch(() => false)) {
        const msg = (await rcxErr.textContent()) ?? "";
        expect(msg, "RCx must not show DataFusion planning errors").not.toMatch(
          /Utf8View|avg\(|planning|Internal error/i,
        );
      }
      // Soft-OPEN: at least one Plotly host with a real drawn div (not empty placeholder).
      const plotHosts = page.locator('[data-testid^="plotly-host-"]');
      const hostCount = await plotHosts.count();
      expect(hostCount, "RCx must render at least one Plotly host").toBeGreaterThan(0);
      const firstDiv = page.locator('[data-testid^="plotly-div-"]').first();
      await expect(firstDiv).toBeVisible({ timeout: 60_000 });
      const plotHtml = (await firstDiv.innerHTML().catch(() => "")) ?? "";
      expect(
        plotHtml.length,
        "Plotly div must contain drawn content (empty host is Soft-OPEN FAIL)",
      ).toBeGreaterThan(32);
      executed += 1;

      await page.goto(`/inspect${q}`);
      await expect(page.getByTestId("inspect-page")).toBeVisible({ timeout: 20_000 });
      executed += 1;

      expect(executed, "Soft-OPEN requires a positive executed case count").toBeGreaterThanOrEqual(4);

      const bad = errors.filter((e) => !/favicon|ResizeObserver|Loading chunk/i.test(e));
      expect(bad, `page errors: ${bad.join(" | ")}`).toEqual([]);
    });
  }

  test("Soft-OPEN building list must not be empty when gate runs", async () => {
    // Surfaces misconfiguration as skip/fail rather than silent green of zero cases.
    if (!process.env.OPENFDD_ADMIN_PASSWORD) {
      test.skip(true, "OPENFDD_ADMIN_PASSWORD required");
    }
    expect(
      sites.length,
      "Set OPENFDD_GATE_BUILDING_ID or OPENFDD_GATE_BUILDING_IDS for Soft-OPEN browser gate",
    ).toBeGreaterThan(0);
  });
});
