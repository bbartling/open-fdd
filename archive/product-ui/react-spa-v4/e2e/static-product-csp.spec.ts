import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import { failIfRequired, stackRequired } from "./requireStack";
import { ensureProductSession } from "./session";

const centralBase =
  process.env.OPENFDD_STATIC_UI_BASE_URL ?? "http://127.0.0.1:8080";

const seededBuildingId = (process.env.OPENFDD_STATIC_UI_BROWSER_BUILDING_ID ?? "").trim();

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

function pathWithSite(path: string): string {
  if (!seededBuildingId) return path;
  const url = new URL(path, centralBase);
  url.searchParams.set("site", seededBuildingId);
  return `${url.pathname}${url.search}`;
}

function tabFromPath(path: string): string {
  const url = new URL(pathWithSite(path), centralBase);
  return url.searchParams.get("tab") || "overview";
}

function isPlaceholderSiteText(text: string | null | undefined): boolean {
  const t = (text ?? "").trim();
  return (
    t.includes("Pick a site") ||
    t.includes("Select or import") ||
    t.includes("Select equipment") ||
    t.includes("no active session")
  );
}

async function assertErrHidden(page: Page): Promise<void> {
  const err = page.locator("#err.show");
  if ((await err.count()) === 0) return;
  const msg = (await err.textContent())?.trim() ?? "";
  if (msg.length > 0) {
    throw new Error(`#err visible: ${msg}`);
  }
}

async function waitForAppBoot(page: Page): Promise<void> {
  await expect(page.locator("#logoutBtn")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator("#tabs")).toBeVisible({ timeout: 15_000 });
}

async function ensureSiteSelected(page: Page, siteId: string): Promise<void> {
  await page.evaluate((site) => {
    const pick = document.getElementById("sitePick") as HTMLSelectElement | null;
    if (!pick) return;
    let opt = pick.querySelector(`option[value="${site}"]`) as HTMLOptionElement | null;
    if (!opt) {
      opt = document.createElement("option");
      opt.value = site;
      opt.textContent = site;
      pick.appendChild(opt);
    }
    pick.value = site;
    pick.dispatchEvent(new Event("change", { bubbles: true }));
  }, siteId);
  await expect(page.locator("#liveTxt")).not.toHaveText("loading…", { timeout: 60_000 });
  await expect(page.locator("#sub")).toContainText(siteId, { timeout: 60_000 });
  const sub = await page.locator("#sub").textContent();
  if (isPlaceholderSiteText(sub)) {
    throw new Error(`site ${siteId} did not load: ${sub ?? ""}`);
  }
  await assertErrHidden(page);
}

async function maybeSelectFirstSite(page: Page): Promise<void> {
  const pick = page.locator("#sitePick");
  const fromQuery =
    new URL(page.url()).searchParams.get("site")?.trim() ||
    seededBuildingId ||
    "";
  if (fromQuery) {
    await ensureSiteSelected(page, fromQuery);
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
    return;
  }

  const option = pick.locator('option[value]:not([value=""])').first();
  if ((await option.count()) === 0) {
    failIfRequired(
      "no selectable site in #sitePick (seed CSV import or set OPENFDD_STATIC_UI_BROWSER_BUILDING_ID)",
    );
    return;
  }
  const value = await option.getAttribute("value");
  if (!value || value.includes("no active")) {
    failIfRequired("site picker has no active building id");
    return;
  }
  await pick.selectOption(value);
  await expect(page.locator("#liveTxt")).not.toHaveText("loading…", { timeout: 60_000 });
  const sub = await page.locator("#sub").textContent();
  if (isPlaceholderSiteText(sub)) {
    throw new Error(`selected site did not load: ${sub ?? ""}`);
  }
  await assertErrHidden(page);

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

async function requireCanvas(page: Page, hostSelector: string): Promise<void> {
  await expect(page.locator(`${hostSelector} canvas`)).toHaveCount(1, { timeout: 60_000 });
}

async function waitForChartsTab(page: Page): Promise<void> {
  await requireCanvas(page, "#tempChart");
}

async function waitForRcxTab(page: Page): Promise<void> {
  await requireCanvas(page, "#mainChart");
}

async function waitForFddTab(page: Page): Promise<void> {
  const fddPick = page.locator("#fddEquipPick");
  if (await fddPick.isVisible()) {
    const fddOpt = fddPick.locator('option[value]:not([value=""])').first();
    if ((await fddOpt.count()) > 0) {
      const fddVal = await fddOpt.getAttribute("value");
      if (fddVal) await fddPick.selectOption(fddVal);
    }
  }
  await expect(async () => {
    await assertErrHidden(page);
    if ((await page.locator("#fddChart canvas").count()) > 0) return;
    const plot = (await page.locator("#plotHint").textContent())?.trim() ?? "";
    if (plot.length > 0 && !isPlaceholderSiteText(plot)) return;
    const rules = (await page.locator("#ruleList").textContent()) ?? "";
    if (rules.includes("No rules match")) return;
    const psy = (await page.locator("#psyHint").textContent()) ?? "";
    if (psy.includes("need oa_t")) return;
    throw new Error("waiting for #fddChart canvas or allowed FDD empty-state");
  }).toPass({ timeout: 90_000 });
}

async function waitForModelTab(page: Page): Promise<void> {
  await requireCanvas(page, "#tree");
}

async function waitForTabRenderMarker(page: Page, path: string): Promise<void> {
  const tab = tabFromPath(path);
  await waitForAppBoot(page);
  await maybeSelectFirstSite(page);
  await assertErrHidden(page);
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

  const sub = await page.locator("#sub").textContent();
  if (isPlaceholderSiteText(sub)) {
    throw new Error(`tab ${tab} still on placeholder site copy: ${sub ?? ""}`);
  }

  if (tab === "charts") {
    await waitForChartsTab(page);
  } else if (tab === "rcx") {
    await waitForRcxTab(page);
  } else if (tab === "fdd") {
    await waitForFddTab(page);
  } else if (tab === "model") {
    await waitForModelTab(page);
  }
}

test.describe("Static product UI CSP (central /app/)", () => {
  test.beforeAll(async ({ request }) => {
    if (process.env.OPENFDD_PLAYWRIGHT_SKIP === "1") {
      failIfRequired("OPENFDD_PLAYWRIGHT_SKIP=1");
    }
    if (stackRequired && !seededBuildingId) {
      failIfRequired(
        "OPENFDD_STATIC_UI_BROWSER_BUILDING_ID unset (run seed_static_ui_browser_site before static CSP spec)",
      );
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
      const target = pathWithSite(path);
      await page.goto(`${centralBase}${target}`, {
        waitUntil: "networkidle",
        timeout: 60_000,
      });
      await expect(page.locator("#loginGate")).toBeHidden({ timeout: 30_000 });
      await waitForTabRenderMarker(page, path);
      await assertErrHidden(page);
      const violations = await page.evaluate(
        () => (window as unknown as { __cspViolations?: CspViolation[] }).__cspViolations ?? [],
      );
      expect(violations, JSON.stringify(violations)).toEqual([]);
    });
  }
});
