/**
 * Programmatic oracle (Streamlit :8501) vs React (:5173) tab / sidebar inventory.
 * Run via Playwright Docker image (host chromium libs are incomplete).
 *
 *   ORACLE_URL=http://127.0.0.1:8501 REACT_URL=http://127.0.0.1:5173 \
 *   docker run --rm --network host -v "$PWD":/work -w /work/frontend/web \
 *     mcr.microsoft.com/playwright:v1.62.1-jammy \
 *     node ../../scripts/parity_tab_inventory.cjs
 */
const { createRequire } = require("module");
const path = require("path");
const fs = require("fs");
// Resolve @playwright/test from frontend/web (script lives in repo scripts/)
const requireFromWeb = createRequire(
  path.join(__dirname, "../frontend/web/package.json"),
);
const { chromium } = requireFromWeb("@playwright/test");

const ORACLE = process.env.ORACLE_URL || "http://127.0.0.1:8501";
const REACT = process.env.REACT_URL || "http://127.0.0.1:5173";
const EVID = process.env.EVID || path.join(process.cwd(), "reports/parity");

const REQUIRED_TABS = [
  "Overview",
  "Data Model",
  "Run Rules",
  "Results by Category",
  "FDD Plots",
  "RCx Plots",
  "Metering",
  "WattLab",
];

const REQUIRED_SIDEBAR = [
  "Sites",
  "Building data",
  "Session restore",
  "Rule tuning",
  "Display & site",
];

async function inventoryOracle(page) {
  await page.goto(ORACLE, { waitUntil: "networkidle", timeout: 90000 });
  await page.waitForTimeout(2500);
  return page.evaluate((tabs) => {
    const body = document.body.innerText || "";
    const foundTabs = tabs.filter((t) => body.includes(t));
    const sidebarBits = {
      sites: /Sites/i.test(body),
      buildingData: /Building data/i.test(body),
      sessionRestore: /Session restore/i.test(body),
      ruleTuning: /Rule tuning/i.test(body),
      displaySite: /Display\s*&\s*site/i.test(body),
      loadZips: /Load zip\(s\)/i.test(body),
      units: /\bimperial\b/i.test(body) && /\bmetric\b/i.test(body),
    };
    const font = getComputedStyle(document.body).fontFamily;
    const bg = getComputedStyle(document.body).backgroundColor;
    return { foundTabs, sidebarBits, font, bg, url: location.href };
  }, REQUIRED_TABS);
}

async function inventoryReact(page) {
  await page.goto(REACT, { waitUntil: "networkidle", timeout: 90000 });
  await page.waitForTimeout(2000);
  return page.evaluate((requiredTabs) => {
    const tabEls = [...document.querySelectorAll("[data-testid='section-tabs'] [data-section]")];
    const tabLabels = tabEls.map((el) => (el.textContent || "").trim());
    const tabIds = tabEls.map((el) => el.getAttribute("data-section"));
    const body = document.body.innerText || "";
    const sidebarBits = {
      sites: Boolean(document.querySelector('[data-testid="sidebar-sites"]')),
      buildingData: Boolean(
        document.querySelector('[data-testid="sidebar-building-data"]'),
      ),
      sessionRestore: /Session restore/i.test(body),
      ruleTuning: Boolean(
        document.querySelector('[data-testid="sidebar-rule-tuning"]'),
      ),
      displaySite: Boolean(
        document.querySelector('[data-testid="sidebar-display"]'),
      ),
      loadZips: Boolean(
        document.querySelector('[data-testid="sidebar-load-zips"]'),
      ),
      units: /\bimperial\b/i.test(body) && /\bmetric\b/i.test(body),
      ruleTuningHeading: /Rule tuning/i.test(body),
      categorySelect: Boolean(
        document.querySelector('[data-testid="sidebar-tune-category"]'),
      ),
    };
    const font = getComputedStyle(document.body).fontFamily;
    const bg = getComputedStyle(document.body).backgroundColor;
    const softChecks = {
      sourceSans: /Source Sans/i.test(font),
      lightBg: bg === "rgb(255, 255, 255)" || bg === "rgba(0, 0, 0, 0)",
      hasHero: /Open FDD/i.test(body) || /open-fdd/i.test(body),
      hasStartHere: /Start here/i.test(body),
    };
    return {
      tabLabels,
      tabIds,
      requiredOk: requiredTabs.every((t) => tabLabels.includes(t)),
      sidebarBits,
      softChecks,
      font,
      bg,
      url: location.href,
    };
  }, REQUIRED_TABS);
}

function assertSidebar(bits, label) {
  const missing = [];
  if (!bits.sites) missing.push("Sites");
  if (!bits.buildingData) missing.push("Building data");
  if (!bits.sessionRestore) missing.push("Session restore");
  if (!bits.ruleTuning) missing.push("Rule tuning");
  if (!bits.displaySite) missing.push("Display & site");
  if (!bits.loadZips) missing.push("Load zip(s)");
  if (!bits.units) missing.push("Units imperial/metric");
  if (missing.length) {
    throw new Error(`${label} sidebar missing: ${missing.join(", ")}`);
  }
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    locale: "en-US",
  });
  const page = await ctx.newPage();
  const report = { oracle: null, react: null, mismatches: [] };

  try {
    report.oracle = await inventoryOracle(page);
    assertSidebar(report.oracle.sidebarBits, "oracle");
    for (const t of REQUIRED_TABS) {
      // Empty Streamlit may hide section radio until frames load — still require text somewhere or skip
      if (!report.oracle.foundTabs.includes(t) && t !== "Overview") {
        // Overview always present; other tabs appear after package load in Streamlit
        report.mismatches.push({
          kind: "oracle_tab_soft",
          tab: t,
          note: "Tab label not in empty-state body (expected until frames load)",
        });
      }
    }
  } catch (e) {
    report.mismatches.push({ kind: "oracle_fail", message: String(e) });
  }

  try {
    report.react = await inventoryReact(page);
    assertSidebar(report.react.sidebarBits, "react");
    if (!report.react.requiredOk) {
      report.mismatches.push({
        kind: "react_tabs",
        expected: REQUIRED_TABS,
        got: report.react.tabLabels,
      });
    }
    if (!report.react.sidebarBits.ruleTuningHeading) {
      report.mismatches.push({ kind: "react_missing", item: "Rule tuning heading" });
    }
    if (!report.react.sidebarBits.categorySelect) {
      report.mismatches.push({ kind: "react_missing", item: "Category select" });
    }
    if (!report.react.softChecks.sourceSans) {
      report.mismatches.push({ kind: "react_font", font: report.react.font });
    }
  } catch (e) {
    report.mismatches.push({ kind: "react_fail", message: String(e) });
  }

  // Hard fail if React missing required chrome
  const hard = report.mismatches.filter(
    (m) =>
      m.kind === "react_tabs" ||
      m.kind === "react_fail" ||
      m.kind === "oracle_fail" ||
      m.kind === "react_missing" ||
      m.kind === "react_font",
  );

  fs.mkdirSync(path.join(EVID, "inventory"), { recursive: true });
  const out = path.join(EVID, "inventory", "tab_sidebar_inventory.json");
  fs.writeFileSync(out, JSON.stringify({ REQUIRED_TABS, REQUIRED_SIDEBAR, ...report }, null, 2));
  console.log(JSON.stringify({ out, hardFail: hard.length, mismatches: report.mismatches }, null, 2));

  await browser.close();
  if (hard.length) process.exit(1);
  console.log("parity_tab_inventory: OK");
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
