#!/usr/bin/env node
// Headless UI acceptance for the Open-FDD NF pages against a LOCAL mock NF (no real NF, no network): the Overview RCx
// dashboard (panels only for modeled equipment, no device picker on charts, the occupancy calendar), the old #rcx /
// #points links, no "All devices" choice anywhere, the FDD tab (summary chips, one open rule, tuning drawer, URL state),
// and a Lite smoke. Synthetic data only: nf-app/tests/fixtures/dashboard_model.mjs.
//
//   OFDD_PLAYWRIGHT_DIR=<folder with node_modules/playwright-core> OFDD_BROWSER=<chrome or edge executable> \
//     node scripts/nf/ui_acceptance.mjs --out <screenshot folder>
// Exit 0 when every check passes; screenshots are written to --out (default: the OS temp folder).
import http from "node:http";
import { readFile, mkdir } from "node:fs/promises";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { dashboardModel, dashboardValue, dashboardFddResults } from "../../nf-app/tests/fixtures/dashboard_model.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const arg = (name, def) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : def; };
const OUT = path.resolve(arg("--out", path.join(os.tmpdir(), "ofdd-ui-acceptance")));
const require = createRequire(path.join(process.env.OFDD_PLAYWRIGHT_DIR || ROOT, "noop.js"));
const { chromium } = require("playwright-core");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png" };

/** A mock NF: same-origin /api/v1/* plus the app's static folder under /apps/static/<appId>/. */
function mockNf({ plant, staticDir, appId }) {
  const now = Date.now();
  const { records, points } = dashboardModel({ plant });
  const results = plant === "full" || plant === "ahu" ? dashboardFddResults(new Date(now).toISOString()) : [];
  const live = points.map((p) => ({ ...p, latestValue: { ts: new Date(now).toISOString(), double: dashboardValue(p.uuid, now) } }));
  const defaultLayer = [...live, ...results];
  const calendars = new Map();
  const runs = [];
  const json = (res, body, code = 200) => { res.writeHead(code, { "Content-Type": "application/json" }); res.end(JSON.stringify(body)); };
  const page = (list, body) => {
    const off = Number(body.pageOffset || 0), size = Number(body.pageSize || 1000);
    return { points: list.slice(off, off + size), totalCount: list.length };
  };
  const tuning = (args) => {
    if (args.rule_id !== "OCC-CALENDAR") return { ok: false, error: "only the occupancy calendar is mocked" };
    const site = args.site, cur = calendars.get(site);
    if (args.action === "save") {
      const doc = JSON.parse(args.overrides);
      const rev = (cur ? cur.revision : 0) + 1;
      calendars.set(site, { revision: rev, calendar: doc.calendar });
      return { ok: true, action: "save", site, revision: rev, written: true, calendar: doc.calendar, source: "saved", active: { site: { revision: rev } } };
    }
    return { ok: true, action: "get", site, calendar: cur ? cur.calendar : null, source: cur ? "saved" : "default", active: cur ? { site: { revision: cur.revision } } : {} };
  };
  return http.createServer(async (req, res) => {
    const url = new URL(req.url, "http://x");
    const p = url.pathname;
    let body = {};
    if (req.method === "POST") { let s = ""; for await (const c of req) s += c; try { body = JSON.parse(s || "{}"); } catch (e) { body = {}; } }
    if (p === "/api/v1/platform/info") return json(res, { provider: "NONE" });
    if (p === "/api/v1/point/query") return json(res, page(body.layer === "model" ? records : defaultLayer, body));
    if (p === "/api/v1/point/data") {
      const from = Date.parse(url.searchParams.get("from") || new Date(now - 7 * 864e5).toISOString()), to = Date.parse(url.searchParams.get("to") || new Date(now).toISOString());
      const win = Math.max(300, parseInt(url.searchParams.get("window") || "3600", 10)) * 1000;
      const count = Number(url.searchParams.get("count") || 10000);
      const data = url.searchParams.getAll("uuids").map((uuid) => {
        const values = [];
        for (let t = Math.ceil(from / win) * win; t < to && values.length < count; t += win) {
          const r = results.find((x) => x.uuid === uuid);
          const v = r ? (r.latestValue ? r.latestValue.double : null) : dashboardValue(uuid, t);
          if (v != null) values.push({ ts: new Date(t).toISOString(), double: v });
        }
        return { uuid, values };
      });
      return json(res, { data });
    }
    if (p === "/api/v1/apps") return json(res, { applications: [{ id: appId, options: [] }] });
    if (p === `/api/v1/apps/${appId}/hooks/tuning` && req.method === "POST") {
      const pid = `pid-${runs.length + 1}`;
      runs.push({ pid, state: "STATE_SUCCEEDED", results: { r: { events: [{ message: JSON.stringify(tuning(body)) }] } } });
      return json(res, { pid });
    }
    if (p === `/api/v1/apps/${appId}/hooks/tuning/runs`) return json(res, { runs: [...runs].reverse() });
    if (p.startsWith("/api/v1/")) return json(res, p.includes("schedules") ? { schedules: [], totalCount: 0 } : {});
    const prefix = `/apps/static/${appId}/`;
    if (!p.startsWith(prefix)) { res.writeHead(404); return res.end(); }
    const rel = decodeURIComponent(p.slice(prefix.length)) || "index.html";
    const file = path.join(staticDir, rel);
    if (!file.startsWith(staticDir)) { res.writeHead(403); return res.end(); }
    try {
      const buf = await readFile(file);
      res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] || "application/octet-stream" });
      res.end(buf);
    } catch (e) { res.writeHead(404); res.end(); }
  });
}

async function serve(opts) {
  const srv = mockNf(opts);
  await new Promise((ok) => srv.listen(0, "127.0.0.1", ok));
  const addr = /** @type {import("node:net").AddressInfo} */ (srv.address());
  return { srv, base: `http://127.0.0.1:${addr.port}/apps/static/${opts.appId}/index.html` };
}

const failures = [];
const check = (ok, what) => { console.log(`${ok ? "PASS" : "FAIL"} ${what}`); if (!ok) failures.push(what); };

async function waitRendered(page) {
  await page.waitForFunction(() => {
    const box = document.getElementById("overviewRcx");
    const cards = box ? [...box.querySelectorAll(".rcx-card")] : [];
    return cards.length > 0 && cards.every((c) => c.hidden || c.querySelector(".chart.rendered") || c.querySelector(".note")?.textContent);
  }, null, { timeout: 60000 });
  await page.waitForTimeout(800);
}
const visibleViews = (page) => page.$$eval("#overviewRcx .rcx-card", (cs) => cs.filter((c) => !c.hidden && !c.closest("section.panel")?.hidden).map((c) => c.dataset.view));

async function main() {
  await mkdir(OUT, { recursive: true });
  const exe = process.env.OFDD_BROWSER;
  const browser = await chromium.launch({ headless: true, ...(exe ? { executablePath: exe } : {}) });
  const shots = [];
  const shot = async (page, name, opts = {}) => { const f = path.join(OUT, name); await page.screenshot({ path: f, fullPage: true, ...opts }); shots.push(f); };
  try {
    const full = await serve({ plant: "full", staticDir: path.join(ROOT, "nf-app/static"), appId: "open-fdd" });
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto(`${full.base}#overview`);
    await waitRendered(page);
    const tabs = await page.$$eval("nav [data-tab], nav a[href^='#']", (as) => as.map((a) => a.dataset.tab || a.getAttribute("href").slice(1)));
    check(!tabs.includes("rcx") && !tabs.includes("points"), `nav has no RCx or Points tab (${tabs.join(", ")})`);
    const views = await visibleViews(page);
    for (const id of ["weekly-fan", "mech-cooling-hours", "hw_reset_scatter", "chw_reset_scatter", "zone_temps"]) check(views.includes(id), `full model: ${id} panel shown`);
    check(!views.includes("ahu-runtime-daily"), "AHU run hours are weekly (no daily AHU panel)");
    const ref = await page.evaluate(() => {
      const el = document.querySelector("#overviewRcx .rcx-card[data-view='weekly-fan'] .chart");
      const o = el && window.echarts.getInstanceByDom(el)?.getOption();
      return o ? o.series.filter((s) => /^schedule-ref:/.test(s.id || "")).map((s) => s.name) : [];
    });
    check(ref.length === 1 && /50 h\/week \(default\)/.test(ref[0]), `weekly AHU runtime has the reference line; nothing saved = the 4.x default (${ref.join("; ")})`);
    const pickers = await page.$$eval("#overviewRcx select", (s) => s.length);
    check(pickers === 0, "no device picker on the dashboard charts");
    const allOpts = await page.$$eval("select option", (os) => os.filter((o) => /^all\b|all devices|all equipment/i.test(o.textContent) || o.value === "all").map((o) => o.textContent));
    check(allOpts.length === 0, `no "All" device choice anywhere (${allOpts.join(", ")})`);
    check(!!(await page.$("#overviewPoints #overviewPointsScope select")), "the device picker lives in the Overview Points section");
    await shot(page, "overview-full.png");
    // occupancy calendar: live line while editing
    await page.click("#overviewOccupancy summary");
    const h0 = await page.textContent("#occHours");
    await page.uncheck("#occ-fri-occupied");
    await page.waitForTimeout(1500);
    const h1 = await page.textContent("#occHours");
    check(/60/.test(h0) && /48/.test(h1), `occupancy calendar: ${h0} -> ${h1} after unchecking Friday`);
    const ref2 = await page.evaluate(() => {
      const el = document.querySelector("#overviewRcx .rcx-card[data-view='weekly-fan'] .chart");
      const o = el && window.echarts.getInstanceByDom(el)?.getOption();
      return o ? o.series.filter((s) => /^schedule-ref:/.test(s.id || "")).map((s) => s.name).join("") : "";
    });
    check(/48 h\/week/.test(ref2), `reference line follows the draft (${ref2})`);
    await page.click("#occSave");
    await page.waitForFunction(() => /Saved \(revision 1\)/.test(document.getElementById("occStatus")?.textContent || ""), null, { timeout: 15000 });
    check(true, "occupancy calendar saved (revision 1)");
    await shot(page, "overview-occupancy.png");
    // old links
    await page.goto(`${full.base}#rcx`);
    await page.waitForTimeout(1500);
    check((await page.evaluate(() => location.hash)).startsWith("#overview"), "#rcx opens Overview");
    await page.goto(`${full.base}#points`);
    await page.waitForTimeout(1500);
    check((await page.evaluate(() => location.hash)).startsWith("#overview"), "#points opens Overview");
    // FDD tab
    await page.goto(`${full.base}#fdd`);
    await page.waitForSelector("#fddList .fdd-item", { timeout: 60000 });
    const chips = await page.$$eval("#fddSummary .fdd-chip", (cs) => cs.map((c) => c.textContent.trim()));
    check(chips.length === 4, `FDD summary chips: ${chips.join(" | ")}`);
    const first = await page.$$eval("#fddList .fdd-item", (is) => is.map((i) => i.dataset.status));
    check(first[0] === "fault", `faults first (${first.join(", ")})`);
    await shot(page, "fdd-summary.png");
    await page.click("#fddList .fdd-item .fdd-row");
    await page.waitForSelector("#fddPlotPanel:not([hidden])", { timeout: 30000 });
    await page.waitForTimeout(1500);
    const open = await page.$$eval("#fddList .fdd-item.open", (x) => x.length);
    check(open === 1, "one rule open at a time");
    const url = await page.evaluate(() => location.href);
    check(/fdd\.rule=/.test(url) && /fdd\.equip=/.test(url), `URL keeps equipment and open rule (${url.split("?")[1] || ""})`);
    await shot(page, "fdd-open-rule.png");
    await page.click("#fddTuneOpen");
    await page.waitForSelector("#fddDrawer:not([hidden])", { timeout: 15000 });
    await shot(page, "fdd-drawer.png", { fullPage: false });
    await page.reload();
    await page.waitForSelector("#fddList .fdd-item.open", { timeout: 60000 });
    check(true, "reload restores the open rule from the URL");
    await page.click("#fddSummary .fdd-chip[data-filter='skipped']");
    await page.waitForTimeout(500);
    const onlySkipped = await page.$$eval("#fddList .fdd-item", (is) => is.every((i) => i.dataset.status === "skipped"));
    check(onlySkipped, "a chip filters the list");
    check(errors.length === 0, `no page errors (${errors.join(" | ")})`);
    full.srv.close();

    // AHU-only model: plant panels hidden
    const ahu = await serve({ plant: "ahu", staticDir: path.join(ROOT, "nf-app/static"), appId: "open-fdd" });
    const p2 = await ctx.newPage();
    await p2.goto(`${ahu.base}#overview`);
    await waitRendered(p2);
    const v2 = await visibleViews(p2);
    check(v2.includes("weekly-fan"), "AHU-only model: weekly AHU runtime shown");
    for (const id of ["mech-cooling-hours", "hw_reset_scatter", "chw_reset_scatter", "zone_temps"]) check(!v2.includes(id), `AHU-only model: ${id} hidden`);
    await shot(p2, "overview-ahu-only.png");
    ahu.srv.close();

    // Lite smoke
    const lite = await serve({ plant: "full", staticDir: path.join(ROOT, "lite/static"), appId: "open-fdd-lite" });
    const p3 = await ctx.newPage();
    const liteErr = [];
    p3.on("pageerror", (e) => liteErr.push(String(e)));
    await p3.goto(`${lite.base}#points`);
    await p3.waitForSelector("#pointRows tr", { timeout: 60000 });
    check((await p3.evaluate(() => location.hash)).startsWith("#overview"), "Lite: #points opens Overview");
    const liteTabs = await p3.$$eval("nav [data-tab], nav a[href^='#']", (as) => as.map((a) => a.dataset.tab || a.getAttribute("href").slice(1)));
    check(!liteTabs.includes("points") && !liteTabs.includes("rcx"), `Lite nav (${liteTabs.join(", ")})`);
    check(liteErr.length === 0, `Lite: no page errors (${liteErr.join(" | ")})`);
    await shot(p3, "lite-overview.png");
    lite.srv.close();
  } finally {
    await browser.close();
  }
  console.log(`screenshots:\n${shots.join("\n")}`);
  if (failures.length) { console.log(`${failures.length} check(s) failed`); process.exit(1); }
  console.log("all UI acceptance checks passed");
}

main().catch((e) => { console.error(e); process.exit(1); });