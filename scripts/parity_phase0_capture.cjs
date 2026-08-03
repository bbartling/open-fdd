#!/usr/bin/env node
/**
 * Phase 0 paired capture: Streamlit openfdd-ui oracle (:8501) vs React (:3000).
 * Run in Playwright docker with --network host.
 */
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const EVID = process.env.EVID || "/openfdd/reports/parity";
const ORACLE = process.env.ORACLE_URL || "http://127.0.0.1:8501/";
const REACT = process.env.REACT_URL || "http://127.0.0.1:3000/";
const ADMIN_USER = process.env.OPENFDD_ADMIN_USER || "admin";
const ADMIN_PASS = process.env.OPENFDD_ADMIN_PASSWORD || "";
const VIEWPORTS = [
  { name: "1440x900", width: 1440, height: 900 },
  { name: "1280x800", width: 1280, height: 800 },
];

// Must match services/ui/app/dashboard_contract.py REQUIRED_MAIN_SECTIONS
const ORACLE_SECTIONS = [
  "Overview",
  "Data Model",
  "Run Rules",
  "Results by Category",
  "FDD Plots",
  "RCx Plots",
  "Metering",
  "WattLab",
];

const REACT_ROUTES = [
  { id: "overview__initial", path: "/" },
  { id: "auth__login", path: "/auth" },
  { id: "jobs__list", path: "/jobs" },
  { id: "upload__page", path: "/upload" },
  { id: "mapping__page", path: "/mapping" },
  { id: "rules__page", path: "/rules" },
  { id: "findings__page", path: "/findings" },
  { id: "reports__page", path: "/reports" },
  { id: "metering__page", path: "/metering" },
  { id: "wattlab__page", path: "/wattlab" },
  { id: "twin__page", path: "/twin" },
];

function slug(s) {
  return String(s)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

function ensureDir(p) {
  fs.mkdirSync(p, { recursive: true });
}

async function measure(page) {
  return page.evaluate(() => {
    const pick = (sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      return {
        sel,
        x: Math.round(r.x),
        y: Math.round(r.y),
        w: Math.round(r.width),
        h: Math.round(r.height),
        fontFamily: cs.fontFamily,
        fontSize: cs.fontSize,
        fontWeight: cs.fontWeight,
        lineHeight: cs.lineHeight,
        background: cs.backgroundColor,
        color: cs.color,
        borderRadius: cs.borderRadius,
        boxShadow: cs.boxShadow,
      };
    };
    const body = getComputedStyle(document.body);
    return {
      url: location.href,
      title: document.title,
      viewport: { w: innerWidth, h: innerHeight },
      body: {
        background: body.backgroundColor,
        color: body.color,
        fontFamily: body.fontFamily,
        fontSize: body.fontSize,
      },
      nodes: {
        sidebar: pick('[data-testid="stSidebar"]') || pick("aside") || pick('[data-testid="app-shell"]'),
        main: pick('[data-testid="stAppViewContainer"]') || pick("main") || pick("#root"),
        nav: pick("nav"),
      },
      heading: (() => {
        const h = document.querySelector("h1, h2, [data-testid='stHeadingWithActionElements'] h1");
        if (!h) return null;
        const r = h.getBoundingClientRect();
        return { text: (h.textContent || "").trim().slice(0, 160), x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
      })(),
      textSnippet: (document.body.innerText || "").replace(/\s+/g, " ").trim().slice(0, 400),
    };
  });
}

async function disableAnim(page) {
  await page.addStyleTag({
    content: `*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important;}`,
  });
}

async function clickOracleSection(page, label) {
  const groups = page.locator('[data-testid="stRadio"]');
  const n = await groups.count();
  for (let i = 0; i < n; i++) {
    const text = await groups.nth(i).innerText();
    if (text.includes("Overview") && (text.includes("Export") || text.includes("WattLab") || text.includes("Metering"))) {
      await groups.nth(i).getByText(label, { exact: true }).click({ timeout: 8000 });
      await page.waitForTimeout(1200);
      return true;
    }
  }
  const t = page.getByText(label, { exact: true });
  if ((await t.count()) > 0) {
    await t.first().click({ timeout: 5000 });
    await page.waitForTimeout(1000);
    return true;
  }
  return false;
}

async function reactLogin(page) {
  if (!ADMIN_PASS) return { ok: false, reason: "no_password" };
  await page.goto(`${REACT.replace(/\/$/, "")}/auth`, { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForTimeout(800);
  const user = page.locator("#auth-username, input[name='username'], input[type='text']").first();
  const pass = page.locator("#auth-password, input[name='password'], input[type='password']").first();
  try {
    await user.waitFor({ state: "visible", timeout: 10000 });
    await pass.waitFor({ state: "visible", timeout: 5000 });
  } catch {
    return { ok: false, reason: "no_login_form", url: page.url() };
  }
  await user.fill(ADMIN_USER);
  await pass.fill(ADMIN_PASS);
  const btn = page.getByRole("button", { name: /^Login$/i }).first();
  if ((await btn.count()) > 0) await btn.click();
  else await page.keyboard.press("Enter");
  await page.waitForTimeout(2000);
  return { ok: true, url: page.url(), authRequiredFalseOk: true };
}

async function captureSide(browser, side, states) {
  const out = [];
  for (const vp of VIEWPORTS) {
    const ctx = await browser.newContext({
      viewport: { width: vp.width, height: vp.height },
      deviceScaleFactor: 1,
      locale: "en-US",
      timezoneId: "UTC",
      colorScheme: "light",
    });
    const page = await ctx.newPage();
    const cons = [];
    const netFail = [];
    page.on("pageerror", (e) => cons.push({ type: "pageerror", message: String(e) }));
    page.on("console", (m) => {
      if (m.type() === "error") cons.push({ type: "console", message: m.text() });
    });
    page.on("response", (r) => {
      if (r.status() >= 400) netFail.push({ url: r.url(), status: r.status() });
    });

    if (side === "react" && ADMIN_PASS) {
      const login = await reactLogin(page);
      fs.writeFileSync(
        path.join(EVID, "console", `react_login_${vp.name}.json`),
        JSON.stringify(login, null, 2),
      );
    }

    for (const st of states) {
      try {
        await st.navigate(page);
      } catch (e) {
        cons.push({ type: "nav", state: st.id, message: String(e) });
      }
      await disableAnim(page);
      await page.waitForTimeout(800);
      const dir = path.join(EVID, side, vp.name);
      ensureDir(dir);
      const file = path.join(dir, `${st.id}.png`);
      await page.screenshot({ path: file, fullPage: false });
      // region crops
      for (const [name, sel] of [
        ["sidebar", '[data-testid="stSidebar"], aside'],
        ["main", '[data-testid="stAppViewContainer"], main, #root'],
      ]) {
        const loc = page.locator(sel).first();
        if ((await loc.count()) > 0) {
          try {
            await loc.screenshot({ path: path.join(dir, `${st.id}__${name}.png`) });
          } catch (_) {}
        }
      }
      const layout = await measure(page);
      ensureDir(path.join(EVID, "measurements"));
      fs.writeFileSync(
        path.join(EVID, "measurements", `${side}_${vp.name}_${st.id}.json`),
        JSON.stringify(layout, null, 2),
      );
      out.push({
        side,
        state: st.id,
        viewport: vp.name,
        screenshot: path.relative(EVID, file),
        layout,
        consoleErrors: cons.filter((c) => c.type !== "nav").slice(-20),
        navErrors: cons.filter((c) => c.type === "nav"),
        networkFailures: netFail.slice(-30),
      });
    }

    ensureDir(path.join(EVID, "console"));
    fs.writeFileSync(
      path.join(EVID, "console", `${side}_${vp.name}.json`),
      JSON.stringify({ console: cons, networkFailures: netFail }, null, 2),
    );
    await ctx.close();
  }
  return out;
}

async function main() {
  ensureDir(EVID);
  for (const d of [
    "oracle/1440x900",
    "oracle/1280x800",
    "react/1440x900",
    "react/1280x800",
    "diff/1440x900",
    "diff/1280x800",
    "measurements",
    "console",
    "network",
  ]) {
    ensureDir(path.join(EVID, d));
  }

  const browser = await chromium.launch({ headless: true });

  const oracleStates = [
    {
      id: "overview__initial",
      navigate: async (page) => {
        await page.goto(ORACLE, { waitUntil: "networkidle", timeout: 90000 });
        await page.waitForTimeout(2500);
        await clickOracleSection(page, "Overview");
      },
    },
    ...ORACLE_SECTIONS.filter((s) => s !== "Overview").map((sec) => ({
      id: `${slug(sec)}__initial`,
      navigate: async (page) => {
        if (!page.url().includes("8501")) {
          await page.goto(ORACLE, { waitUntil: "networkidle", timeout: 90000 });
          await page.waitForTimeout(2000);
        }
        const ok = await clickOracleSection(page, sec);
        if (!ok) throw new Error(`section not found: ${sec}`);
      },
    })),
  ];

  const reactStates = REACT_ROUTES.map((r) => ({
    id: r.id,
    navigate: async (page) => {
      const base = REACT.replace(/\/$/, "");
      await page.goto(`${base}${r.path}`, { waitUntil: "networkidle", timeout: 60000 });
      await page.waitForTimeout(1000);
    },
  }));

  console.log("capturing oracle…");
  const oracle = await captureSide(browser, "oracle", oracleStates);
  console.log("capturing react…");
  const react = await captureSide(browser, "react", reactStates);

  const matrix = {
    capturedAt: new Date().toISOString(),
    oracleUrl: ORACLE,
    reactUrl: REACT,
    viewports: VIEWPORTS.map((v) => v.name),
    oracleStates: oracle.map((e) => ({ id: e.state, viewport: e.viewport, screenshot: e.screenshot })),
    reactStates: react.map((e) => ({ id: e.state, viewport: e.viewport, screenshot: e.screenshot })),
    entries: [...oracle, ...react],
  };
  fs.writeFileSync(path.join(EVID, "state-matrix.json"), JSON.stringify(matrix, null, 2));
  fs.writeFileSync(
    path.join(EVID, "screenshot-manifest.json"),
    JSON.stringify(
      {
        capturedAt: matrix.capturedAt,
        files: [...oracle, ...react].map((e) => e.screenshot),
      },
      null,
      2,
    ),
  );

  await browser.close();
  console.log(
    JSON.stringify(
      {
        ok: true,
        oracleShots: oracle.length,
        reactShots: react.length,
      },
      null,
      2,
    ),
  );
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
