import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import { failIfRequired, stackRequired } from "./requireStack";
import { ensureProductSession } from "./session";

const centralBase =
  process.env.OPENFDD_STATIC_UI_BASE_URL ?? "http://127.0.0.1:8080";

type CspViolation = {
  violatedDirective: string;
  blockedURI: string;
  sample: string;
};

const TAB_PATHS = [
  "/app/",
  "/app/?tab=charts",
  "/app/?tab=points",
  "/app/?tab=rcx",
  "/app/?tab=fdd",
  "/app/?tab=model",
];

function tabFromPath(path: string): string {
  const url = new URL(path, centralBase);
  return url.searchParams.get("tab") || "overview";
}

async function waitForTabRenderMarker(page: Page, path: string): Promise<void> {
  const tab = tabFromPath(path);
  switch (tab) {
    case "charts":
      await expect(page.locator("#tab-charts.on")).toBeVisible({ timeout: 30_000 });
      await page.locator("#tempChart canvas").waitFor({ state: "attached", timeout: 45_000 });
      break;
    case "points":
      await expect(page.locator("#tab-points.on")).toBeVisible({ timeout: 30_000 });
      await expect(page.locator("#pointRows")).toBeVisible({ timeout: 30_000 });
      break;
    case "rcx":
      await expect(page.locator("#tab-rcx.on")).toBeVisible({ timeout: 30_000 });
      await page.locator("#mainChart canvas").waitFor({ state: "attached", timeout: 45_000 });
      break;
    case "fdd":
      await expect(page.locator("#tab-fdd.on")).toBeVisible({ timeout: 30_000 });
      await expect(page.locator("#ruleList")).toBeVisible({ timeout: 30_000 });
      break;
    case "model":
      await expect(page.locator("#tab-model.on")).toBeVisible({ timeout: 30_000 });
      await expect(page.locator("#tree")).toBeVisible({ timeout: 30_000 });
      break;
    default:
      await expect(page.locator("#summary .stat").first()).toBeVisible({ timeout: 45_000 });
      break;
  }
}

test.describe("Static product UI CSP (central /app/)", () => {
  test.beforeAll(async ({ request }) => {
    if (process.env.OPENFDD_PLAYWRIGHT_SKIP === "1") {
      failIfRequired("OPENFDD_PLAYWRIGHT_SKIP=1");
    }
    let res;
    try {
      res = await request.get(`${centralBase}/api/health`, { timeout: 5_000 });
    } catch (err) {
      if (stackRequired) {
        throw err instanceof Error ? err : new Error(String(err));
      }
      test.skip(true, `Central unreachable at ${centralBase}`);
      return;
    }
    if (!res.ok()) {
      failIfRequired(`Central not healthy (HTTP ${res.status()})`);
    }
  });

  test.beforeEach(async ({ page, request }) => {
    await page.addInitScript(() => {
      const list: CspViolation[] = [];
      (window as unknown as { __cspViolations?: CspViolation[] }).__cspViolations = list;
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

  for (const path of TAB_PATHS) {
    test(`no CSP violations on ${path}`, async ({ page }) => {
      await page.goto(`${centralBase}${path.replace("/app/", "/app/")}`, {
        waitUntil: "networkidle",
        timeout: 60_000,
      });
      await expect(page.locator("#loginGate")).toBeHidden({ timeout: 30_000 });
      await waitForTabRenderMarker(page, path);
      const violations = await page.evaluate(
        () => (window as unknown as { __cspViolations?: CspViolation[] }).__cspViolations ?? [],
      );
      expect(violations, JSON.stringify(violations)).toEqual([]);
    });
  }
});
