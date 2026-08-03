/**
 * Programmatic oracle (Streamlit :8501) vs React (:5173) tab / sidebar / Overview inventory.
 *
 *   ORACLE_URL=http://127.0.0.1:8501 REACT_URL=http://127.0.0.1:5173 \
 *   docker run --rm --network host -v "$PWD":/work -w /work \
 *     mcr.microsoft.com/playwright:v1.62.1-jammy \
 *     node scripts/parity_tab_inventory.cjs
 */
const { createRequire } = require("module");
const path = require("path");
const fs = require("fs");
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

const OVERVIEW_SECTIONS = [
  "Engineering Findings",
  "Building schedule",
  "Motor run hours",
  "Mechanical cooling",
  "Economizer",
  "BAS vs web",
  "Devices by type",
  "Data inspection",
];

async function inventoryOracle(page) {
  await page.goto(ORACLE, { waitUntil: "networkidle", timeout: 90000 });
  await page.waitForTimeout(2500);
  return page.evaluate((tabs) => {
    const body = document.body.innerText || "";
    return {
      foundTabs: tabs.filter((t) => body.includes(t)),
      sidebarBits: {
        sites: /Sites/i.test(body),
        buildingData: /Building data/i.test(body),
        sessionRestore: /Session restore/i.test(body),
        ruleTuning: /Rule tuning/i.test(body),
        displaySite: /Display\s*&\s*site/i.test(body),
        displayBeforeTuning:
          body.indexOf("Display & site") >= 0 &&
          body.indexOf("Rule tuning") >= 0 &&
          body.indexOf("Display & site") < body.indexOf("Rule tuning"),
        loadZips: /Load zip\(s\)/i.test(body),
        units: /\bimperial\b/i.test(body) && /\bmetric\b/i.test(body),
      },
      font: getComputedStyle(document.body).fontFamily,
      bg: getComputedStyle(document.body).backgroundColor,
      url: location.href,
    };
  }, REQUIRED_TABS);
}

async function inventoryReact(page) {
  await page.goto(REACT, { waitUntil: "networkidle", timeout: 90000 });
  await page.waitForTimeout(2000);
  return page.evaluate(
    ({ requiredTabs, overviewSections }) => {
      const tabEls = [
        ...document.querySelectorAll(
          "[data-testid='section-tabs'] [data-section]",
        ),
      ];
      const tabLabels = tabEls.map((el) => (el.textContent || "").trim());
      const body = document.body.innerText || "";
      const radios = [
        ...document.querySelectorAll(
          '[data-testid="section-tabs"] input[type="radio"]',
        ),
      ];
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
        categorySelect: Boolean(
          document.querySelector('[data-testid="sidebar-tune-category"]'),
        ),
        displayBeforeTuning: (() => {
          const d = document.querySelector('[data-testid="sidebar-display"]');
          const r = document.querySelector(
            '[data-testid="sidebar-rule-tuning"]',
          );
          if (!d || !r) return false;
          return Boolean(
            d.compareDocumentPosition(r) & Node.DOCUMENT_POSITION_FOLLOWING,
          );
        })(),
        nestedRulePane: (() => {
          const el = document.querySelector('[data-testid="sidebar-tune-rules"]');
          if (!el) return false;
          const st = getComputedStyle(el);
          return st.maxHeight !== "none" && st.maxHeight !== "" && st.overflowY === "auto";
        })(),
      };
      const overview = {
        populated: Boolean(
          document.querySelector('[data-testid="overview-populated"]'),
        ),
        emptyHero: Boolean(document.querySelector('[data-testid="oracle-hero"]')),
        sectionsPresent: overviewSections.filter((s) => body.includes(s)),
        sectionTestIds: [
          "overview-eng-findings",
          "overview-schedule",
          "overview-motor-runtime",
          "overview-mech-cooling",
          "overview-economizer",
          "overview-bas-web-oat",
          "overview-devices-by-type",
          "overview-data-inspection",
        ].filter((id) => Boolean(document.querySelector(`[data-testid="${id}"]`))),
      };
      return {
        tabLabels,
        requiredOk: requiredTabs.every((t) => tabLabels.includes(t)),
        radioCount: radios.length,
        sidebarBits,
        overview,
        softChecks: {
          sourceSans: /Source Sans/i.test(
            getComputedStyle(document.body).fontFamily,
          ),
          hasPlotly: typeof window.Plotly !== "undefined",
        },
        font: getComputedStyle(document.body).fontFamily,
        url: location.href,
      };
    },
    { requiredTabs: REQUIRED_TABS, overviewSections: OVERVIEW_SECTIONS },
  );
}

function assertSidebar(bits, label) {
  const missing = [];
  if (!bits.sites) missing.push("Sites");
  if (!bits.buildingData) missing.push("Building data");
  if (!bits.sessionRestore) missing.push("Session restore");
  if (!bits.ruleTuning) missing.push("Rule tuning");
  if (!bits.displaySite) missing.push("Display & site");
  if (!bits.loadZips) missing.push("Load zip(s)");
  if (!bits.units) missing.push("Units");
  if (missing.length) throw new Error(`${label} sidebar missing: ${missing.join(", ")}`);
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
    try {
      assertSidebar(report.oracle.sidebarBits, "oracle");
    } catch (e) {
      // Streamlit empty/collapsed chrome can hide sidebar text in nested frames.
      report.mismatches.push({
        kind: "oracle_sidebar_soft",
        message: String(e),
      });
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
    if (report.react.radioCount < 8) {
      report.mismatches.push({
        kind: "react_radios",
        count: report.react.radioCount,
      });
    }
    if (!report.react.sidebarBits.displayBeforeTuning) {
      report.mismatches.push({
        kind: "sidebar_order",
        item: "Display & site must precede Rule tuning",
      });
    }
    if (report.react.sidebarBits.nestedRulePane) {
      report.mismatches.push({
        kind: "nested_rule_pane",
        item: "Rule tuning must not use nested max-height scroll pane",
      });
    }
    if (!report.react.softChecks.sourceSans) {
      report.mismatches.push({ kind: "react_font", font: report.react.font });
    }
    if (!report.react.softChecks.hasPlotly) {
      report.mismatches.push({ kind: "plotly_missing" });
    }
  } catch (e) {
    report.mismatches.push({ kind: "react_fail", message: String(e) });
  }

  const hard = report.mismatches.filter((m) =>
    [
      "react_tabs",
      "react_fail",
      "oracle_fail",
      "react_radios",
      "sidebar_order",
      "nested_rule_pane",
      "react_font",
      "plotly_missing",
    ].includes(m.kind),
  );

  fs.mkdirSync(path.join(EVID, "inventory"), { recursive: true });
  const out = path.join(EVID, "inventory", "tab_sidebar_inventory.json");
  fs.writeFileSync(
    out,
    JSON.stringify({ REQUIRED_TABS, OVERVIEW_SECTIONS, ...report }, null, 2),
  );
  console.log(
    JSON.stringify({ out, hardFail: hard.length, mismatches: report.mismatches }, null, 2),
  );
  await browser.close();
  if (hard.length) process.exit(1);
  console.log("parity_tab_inventory: OK");
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
