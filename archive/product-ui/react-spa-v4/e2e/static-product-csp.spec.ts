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

async function waitForAppBoot(page: Page): Promise<void> {
  await expect(page.locator("#logoutBtn")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator("#tabs")).toBeVisible({ timeout: 15_000 });
}

async function maybeSelectFirstSite(page: Page): Promise<void> {
  const pick = page.locator("#sitePick");
  const option = pick.locator('option[value]:not([value=""])').first();
  if ((await option.count()) === 0) return;
  const value = await option.getAttribute("value");
  if (!value || value.includes("no active")) return;
  await pick.selectOption(value);
  await expect(page.locator("#liveTxt")).not.toHaveText("loading…", { timeout: 60_000 });
  const equipPick = page.locator("#equipPick");
  if (await equipPick.isEnabled()) {
    const eq = equipPick.locator('option[value]:not([value=""])').first();
    if ((await eq.count()) > 0) {
      const eqVal = await eq.getAttribute("value");
      if (eqVal) {
        await equipPick.selectOption(eqVal);
        await expect(page.locator("#liveTxt")).not.toHaveText("loading…", { timeout: 60_000 });
      }
    }
  }
}

async function waitForCanvasOrHint(
  page: Page,
  hostSelector: string,
  hintSelector: string,
  hintReady: (text: string | null) => boolean,
): Promise<void> {
  await expect(async () => {
    if ((await page.locator(`${hostSelector} canvas`).count()) > 0) {
      return;
    }
    const text = await page.locator(hintSelector).textContent();
    if (hintReady(text)) {
      return;
    }
    throw new Error(`waiting for chart canvas or hint (${hostSelector}, ${hintSelector})`);
  }).toPass({ timeout: 45_000 });
}

async function waitForChartsTabChartOrEmpty(page: Page): Promise<void> {
  await expect(async () => {
    if ((await page.locator("#tempChart canvas").count()) > 0) return;
    if ((await page.locator("#wxChart canvas").count()) > 0) return;
    const psy = await page.locator("#psyHint").textContent();
    if (psy?.includes("need oa_t")) return;
    const sub = await page.locator("#sub").textContent();
    if (sub?.includes("Select or import")) return;
    throw new Error("waiting for charts tab canvas or psyHint empty-state");
  }).toPass({ timeout: 45_000 });
}

async function waitForTabRenderMarker(page: Page, path: string): Promise<void> {
  const tab = tabFromPath(path);
  await waitForAppBoot(page);
  await maybeSelectFirstSite(page);
  await expect(page.locator(`#tabs button[data-tab="${tab}"]`)).toHaveClass(/\bon\b/, {
    timeout: 30_000,
  });
  const panel = page.locator(`#tab-${tab}`);
  await expect(panel).toHaveClass(/\bon\b/, { timeout: 15_000 });
  const markerByTab: Record<string, string> = {
    charts: "#tempChart",
    points: "#pointRows",
    rcx: "#mainChart",
    fdd: "#ruleList",
    model: "#tree",
    overview: "#summary",
  };
  await expect(panel.locator(markerByTab[tab] ?? "#summary")).toBeAttached({ timeout: 15_000 });

  if (tab === "charts") {
    await waitForChartsTabChartOrEmpty(page);
  }
  if (tab === "rcx") {
    await waitForCanvasOrHint(page, "#mainChart", "#rcxLoadMsg", (text) =>
      Boolean(text && text !== "Loading…"),
    );
  }
  if (tab === "fdd") {
    const fddPick = page.locator("#fddEquipPick");
    if (await fddPick.isVisible()) {
      const fddOpt = fddPick.locator('option[value]:not([value=""])').first();
      if ((await fddOpt.count()) > 0) {
        const fddVal = await fddOpt.getAttribute("value");
        if (fddVal) await fddPick.selectOption(fddVal);
      }
    }
    await expect(async () => {
      if ((await page.locator("#fddChart canvas").count()) > 0) return;
      const plot = (await page.locator("#plotHint").textContent())?.trim() ?? "";
      if (plot.length > 0) return;
      const rules = await page.locator("#ruleList").textContent();
      if (rules?.includes("No rules match")) return;
      const err = (await page.locator("#err.show").textContent())?.trim() ?? "";
      if (err.length > 0) return;
      throw new Error("waiting for FDD chart canvas or empty-state hint");
    }).toPass({ timeout: 60_000 });
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
      test.setTimeout(180_000);
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
