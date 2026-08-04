#!/usr/bin/env node
/**
 * UXR-00 capture: screenshots + DOM measurements for V19/V20/V21/Open-FDD.
 * Run inside Playwright docker with --network host.
 *
 *   EVID=/home/ben/open-fdd/reports/uxr-00/03c0023_74c375e
 *   node scripts/uxr00_capture.mjs
 */
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const EVID = process.env.EVID || "/home/ben/open-fdd/reports/uxr-00/03c0023_74c375e";
const VIEWPORTS = [
  { name: "1440x900", width: 1440, height: 900 },
  { name: "1280x800", width: 1280, height: 800 },
];

const V19_SECTIONS = [
  "Overview",
  "Data Model",
  "Run Rules",
  "Results by Category",
  "FDD Plots",
  "RCx Plots",
  "Metering",
  "Export",
];
const V20_PAGES = ["Uploads", "Fuel dashboard", "Twin / calibrate", "ECMs"];
const OFDD_ROUTES = [
  "/",
  "/auth",
  "/jobs",
  "/upload",
  "/mapping",
  "/rules",
  "/findings",
  "/reports",
  "/metering",
  "/wattlab",
  "/twin",
  "/login",
];

function slug(s) {
  return String(s)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

async function measureLayout(page) {
  return page.evaluate(() => {
    const body = document.body.getBoundingClientRect();
    const pick = (sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      return {
        sel,
        x: r.x,
        y: r.y,
        w: r.width,
        h: r.height,
        fontFamily: cs.fontFamily,
        fontSize: cs.fontSize,
        fontWeight: cs.fontWeight,
        lineHeight: cs.lineHeight,
        background: cs.backgroundColor,
        color: cs.color,
        borderRadius: cs.borderRadius,
        boxShadow: cs.boxShadow,
        padding: cs.padding,
      };
    };
    // Streamlit sidebar / main heuristics + Open-FDD shell
    const candidates = [
      '[data-testid="stSidebar"]',
      "section[data-testid='stSidebar']",
      ".stSidebar",
      '[data-testid="app-shell"]',
      "aside",
      "nav",
      "main",
      '[data-testid="stAppViewContainer"]',
      "#root",
    ];
    const nodes = {};
    for (const sel of candidates) {
      const m = pick(sel);
      if (m) nodes[sel] = m;
    }
    // First heading
    const h1 = document.querySelector("h1, [data-testid='stHeadingWithActionElements'] h1, h2");
    let heading = null;
    if (h1) {
      const r = h1.getBoundingClientRect();
      const cs = getComputedStyle(h1);
      heading = {
        text: (h1.textContent || "").trim().slice(0, 120),
        x: r.x,
        y: r.y,
        w: r.width,
        h: r.height,
        fontFamily: cs.fontFamily,
        fontSize: cs.fontSize,
        fontWeight: cs.fontWeight,
      };
    }
    return {
      url: location.href,
      title: document.title,
      body: { w: body.width, h: body.height },
      nodes,
      heading,
      testIds: [...document.querySelectorAll("[data-testid]")]
        .map((e) => e.getAttribute("data-testid"))
        .filter(Boolean)
        .slice(0, 80),
    };
  });
}

async function shot(page, outPath) {
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  await page.waitForTimeout(800);
  await page.screenshot({ path: outPath, fullPage: true });
}

async function clickStreamlitRadio(page, label) {
  // Prefer the main-section stRadio group that lists Overview…Export / Uploads…ECMs.
  const groups = page.locator('[data-testid="stRadio"]');
  const n = await groups.count();
  for (let i = 0; i < n; i++) {
    const text = await groups.nth(i).innerText();
    if (text.includes(label) && (text.includes("Export") || text.includes("ECMs") || text.includes("Uploads"))) {
      await groups.nth(i).getByText(label, { exact: true }).click({ timeout: 8000 });
      await page.waitForTimeout(1500);
      return true;
    }
  }
  // Fallback: any exact text
  const byLabel = page.getByText(label, { exact: true });
  if ((await byLabel.count()) > 0) {
    await byLabel.first().click({ timeout: 5000 });
    await page.waitForTimeout(1200);
    return true;
  }
  return false;
}

async function waitV19Populated(page) {
  for (let i = 0; i < 45; i++) {
    const ready = await page.evaluate(() => {
      const t = document.body.innerText || "";
      return t.includes("Overview") && t.includes("Export") && t.includes("Run Rules");
    });
    if (ready) return;
    await page.waitForTimeout(2000);
  }
  throw new Error("Vibe19 sections not ready (bootstrap/package not loaded?)");
}

async function captureApp(browser, cfg) {
  const results = [];
  for (const vp of VIEWPORTS) {
    const context = await browser.newContext({
      viewport: { width: vp.width, height: vp.height },
      deviceScaleFactor: 1,
      colorScheme: "light",
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));

    await page.goto(cfg.url, { waitUntil: "networkidle", timeout: 60000 });
    await page.waitForTimeout(1500);

    const states = cfg.states || [{ id: "start", navigate: async () => {} }];
    for (const st of states) {
      try {
        await st.navigate(page);
      } catch (e) {
        errors.push(`nav:${st.id}:${e.message || e}`);
      }
      await page.waitForTimeout(cfg.settleMs || 1500);
      const base = path.join(EVID, "screenshots", cfg.app, vp.name);
      const file = path.join(base, `${slug(st.id)}.png`);
      await shot(page, file);
      const layout = await measureLayout(page);
      results.push({
        app: cfg.app,
        state: st.id,
        viewport: vp.name,
        screenshot: path.relative(EVID, file),
        layout,
        pageErrors: [...errors],
      });
    }
    await context.close();
  }
  return results;
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const all = [];
  const manifest = { capturedAt: new Date().toISOString(), entries: [] };

  // Vibe 19 — start + each section (requires VIBE19_BOOTSTRAP Building 100)
  const v19States = [
    {
      id: "populated-start",
      navigate: async (page) => {
        await waitV19Populated(page);
      },
    },
    ...V19_SECTIONS.map((sec) => ({
      id: `section-${slug(sec)}`,
      navigate: async (page) => {
        await waitV19Populated(page);
        const ok = await clickStreamlitRadio(page, sec);
        if (!ok) throw new Error(`section radio not found: ${sec}`);
      },
    })),
  ];
  all.push(
    ...(await captureApp(browser, {
      app: "v19",
      url: "http://127.0.0.1:8519/",
      states: v19States,
      settleMs: 2500,
    })),
  );

  // Vibe 20 workflow pages
  const v20States = [
    { id: "empty-start", navigate: async () => {} },
    ...V20_PAGES.map((p) => ({
      id: `page-${slug(p)}`,
      navigate: async (page) => {
        const ok = await clickStreamlitRadio(page, p);
        if (!ok) throw new Error(`workflow radio not found: ${p}`);
      },
    })),
  ];
  all.push(
    ...(await captureApp(browser, {
      app: "v20",
      url: "http://127.0.0.1:8520/",
      states: v20States,
      settleMs: 2000,
    })),
  );

  // Vibe 21 — home + health API note (UI is index / webgl)
  all.push(
    ...(await captureApp(browser, {
      app: "v21",
      url: "http://127.0.0.1:5050/",
      states: [
        { id: "home-index", navigate: async () => {} },
        {
          id: "api-health-json",
          navigate: async (page) => {
            await page.goto("http://127.0.0.1:5050/api/v1/health", {
              waitUntil: "domcontentloaded",
            });
          },
        },
        {
          id: "api-models",
          navigate: async (page) => {
            await page.goto("http://127.0.0.1:5050/api/v1/models", {
              waitUntil: "domcontentloaded",
            });
          },
        },
      ],
      settleMs: 1000,
    })),
  );

  // Open-FDD routes via Caddy :80 (LAN-like)
  const ofddStates = OFDD_ROUTES.map((route) => ({
    id: `route-${slug(route === "/" ? "home" : route)}`,
    navigate: async (page) => {
      await page.goto(`http://127.0.0.1${route}`, {
        waitUntil: "networkidle",
        timeout: 30000,
      });
    },
  }));
  // first load base then each route as own state with goto in navigate
  all.push(
    ...(await captureApp(browser, {
      app: "openfdd",
      url: "http://127.0.0.1/",
      states: ofddStates,
      settleMs: 1200,
    })),
  );

  await browser.close();

  const layoutPath = path.join(EVID, "reference-layout.json");
  fs.writeFileSync(layoutPath, JSON.stringify({ measurements: all }, null, 2));

  for (const row of all) {
    manifest.entries.push({
      app: row.app,
      state: row.state,
      viewport: row.viewport,
      screenshot: row.screenshot,
      url: row.layout?.url,
      heading: row.layout?.heading?.text || null,
      errorCount: (row.pageErrors || []).length,
    });
  }
  fs.writeFileSync(
    path.join(EVID, "screenshot-manifest.json"),
    JSON.stringify(manifest, null, 2),
  );
  console.log(
    `OK captured ${all.length} states → ${layoutPath} manifest=${manifest.entries.length}`,
  );
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
