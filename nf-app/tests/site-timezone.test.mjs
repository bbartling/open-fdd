// node --test nf-app/tests/site-timezone.test.mjs
// 5.0.13 (#1584): the site timezone chain (model tz -> app option -> NF Sites API -> browser -> UTC) in Full AND Lite,
// against the mock's "real-nf" profile: no site tz, an empty /api/v1/sites, platform timezone Etc/UTC.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import net from "node:net";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const MOCK = fileURLToPath(new URL("../dev/mock-nf.mjs", import.meta.url));
const SRC = { full: readFileSync(new URL("../static/charts.js", import.meta.url), "utf8"),
  lite: readFileSync(new URL("../../lite/static/charts.js", import.meta.url), "utf8") };
const SCHEDULE = readFileSync(new URL("../static/schedule.js", import.meta.url), "utf8");
const freePort = () => new Promise((ok, no) => { const s = net.createServer(); s.once("error", no); s.listen(0, "127.0.0.1", () => { const { port } = s.address(); s.close(() => ok(port)); }); });

const mocks = [];
async function startMock(env) {
  const port = await freePort(), base = `http://127.0.0.1:${port}`;
  const child = spawn(process.execPath, [MOCK, String(port)], { stdio: ["ignore", "pipe", "inherit"], env: { ...process.env, ...env } });
  await new Promise((ok, no) => { child.once("error", no); child.stdout.on("data", (d) => { if (String(d).includes("mock NF:")) ok(); }); });
  mocks.push(child);
  return base;
}
let bare, withOption;      // real-nf profile: nothing configured / app option America/Chicago
before(async () => {
  bare = await startMock({ MOCK_PROFILE: "real-nf" });
  withOption = await startMock({ MOCK_PROFILE: "real-nf", MOCK_APP_TIMEZONE: "America/Chicago" });
});
after(() => mocks.forEach((c) => c.kill()));

/** charts.js in a vm context whose api() talks to the mock; the browser zone is faked. */
function page(edition, base, browserZone = "UTC") {
  const DTF = function (l, o) { return l === undefined && o === undefined ? { resolvedOptions: () => ({ timeZone: browserZone }) } : new Intl.DateTimeFormat(l, o); };
  const location = { pathname: "/api/v1/apps/static/open-fdd/", href: "https://nf.example.test/api/v1/apps/static/open-fdd/", search: "" };
  const ctx = vm.createContext({
    URL, URLSearchParams, Date, Math, Object, Number, String, Map, Set, Promise, Array, JSON, encodeURIComponent,
    Intl: { ...Intl, DateTimeFormat: Object.assign(DTF, { supportedLocalesOf: Intl.DateTimeFormat.supportedLocalesOf }) },
    LT: { palette: [], axisLine: "", label: "", split: "", tipBg: "", tipText: "", legend: "", panel: "", filler: "", dark: false },
    location, esc: (s) => String(s ?? ""),
    history: { pushState(_s, _t, h) { location.href = String(h); location.search = new URL(h).search; }, replaceState(_s, _t, h) { location.href = String(h); location.search = new URL(h).search; } },
    api: async (path, body) => {
      const r = await fetch(base + path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
      return r.json();
    },
  });
  if (edition === "full") vm.runInContext(SCHEDULE, ctx, { filename: "schedule.js" });
  vm.runInContext(SRC[edition], ctx, { filename: "charts.js" });
  ctx.get = (n) => vm.runInContext(n, ctx);
  ctx.siteRecord = async () => ((await ctx.api("/api/v1/point/query", { layer: "model", pageSize: 1000 })).points || []).find((p) => p.pointType === "SITE");
  ctx.control = () => ({ innerHTML: "", classList: { add() {} } });
  return ctx;
}

for (const edition of ["full", "lite"]) {
  test(`${edition}: real-NF profile has no site tz, an empty Sites list and platform zone Etc/UTC`, async () => {
    const p = page(edition, bare);
    const site = await p.siteRecord();
    assert.ok(site && site.attrs, "model has a site");
    assert.equal(site.attrs.tz, undefined);
    assert.deepEqual((await p.api("/api/v1/sites")).sites, []);
    assert.equal((await p.api("/api/v1/platform/info")).timezone, "Etc/UTC");
  });

  test(`${edition}: nothing configured reads "UTC (fallback)" on the range control`, async () => {
    const p = page(edition, bare);
    await p.get("loadSiteTimeZoneSources")();
    const info = p.get("resolveSiteTimeZone")(await p.siteRecord());
    assert.ok(info);
    assert.deepEqual({ zone: info.zone, source: info.source, fallback: info.fallback, label: info.label },
      { zone: "UTC", source: "none", fallback: true, label: "UTC (fallback)" });
    const el = p.control();
    p.get("renderRangeControl")(el, { key: "tz.test", siteTz: info.zone });
    assert.match(el.innerHTML, /<span class="sub">UTC \(fallback\)<\/span>/);
  });

  test(`${edition}: a non-UTC browser zone is the next fallback and says so`, async () => {
    const p = page(edition, bare, "America/Denver");
    await p.get("loadSiteTimeZoneSources")();
    const info = p.get("resolveSiteTimeZone")(await p.siteRecord());
    assert.ok(info);
    assert.equal(info.zone, "America/Denver");
    assert.equal(info.label, "America/Denver (browser fallback)");
  });

  test(`${edition}: the app option wins over the browser and shows America/Chicago on every range control`, async () => {
    const p = page(edition, withOption, "America/Denver");
    await p.get("loadSiteTimeZoneSources")();
    const info = p.get("resolveSiteTimeZone")(await p.siteRecord());
    assert.ok(info);
    assert.deepEqual({ zone: info.zone, source: info.source, fallback: info.fallback, label: info.label },
      { zone: "America/Chicago", source: "app option", fallback: false, label: "America/Chicago" });
    for (const key of ["overview", "charts", "points", "rcx", "export", "lite.chart"]) {
      const el = p.control();
      p.get("renderRangeControl")(el, { key, siteTz: info.zone });
      assert.match(el.innerHTML, /<span class="sub">America\/Chicago<\/span>/, key);
    }
  });

  test(`${edition}: a custom range round-trips through the URL as the same epoch ms in the resolved zone`, async () => {
    const p = page(edition, withOption);
    await p.get("loadSiteTimeZoneSources")();
    const zone = p.get("resolveSiteTimeZone")(await p.siteRecord()).zone;
    const fromMs = p.get("dateTimeInputMs")("2026-03-08T01:30", zone), toMs = p.get("dateTimeInputMs")("2026-03-08T03:30", zone);
    assert.equal(fromMs, Date.UTC(2026, 2, 8, 7, 30), "01:30 CST = 07:30Z");
    assert.equal(toMs, Date.UTC(2026, 2, 8, 8, 30), "03:30 CDT = 08:30Z (DST skipped 02:xx)");
    p.get("setChartRangeState")("points", { preset: "custom", fromMs, toMs });
    const back = p.get("getChartRangeState")("points");
    assert.deepEqual([back.preset, back.fromMs, back.toMs], ["custom", fromMs, toMs]);
    assert.equal(p.get("dateTimeInputValue")(fromMs, zone), "2026-03-08T01:30");
  });

  test(`${edition}: a model site tz beats the app option; a bad option is ignored`, () => {
    const p = page(edition, bare);
    p.get("setSiteTimeZoneSources")({ appOption: "America/Chicago" });
    assert.equal(p.get("resolveSiteTimeZone")({ attrs: { tz: "Europe/Berlin" } }).zone, "Europe/Berlin");
    assert.equal(p.get("resolveSiteTimeZone")({ attrs: { timezone: "Asia/Tokyo" } }).source, "model site");
    p.get("setSiteTimeZoneSources")({ appOption: "Central Time" });
    assert.equal(p.get("resolveSiteTimeZone")({ attrs: {} }, { browser: false }).label, "UTC (fallback)");
  });

  test(`${edition}: NF Sites API timezone is used when the model and the option have none (matched by id or name)`, () => {
    const p = page(edition, bare);
    p.get("setSiteTimeZoneSources")({ sites: [{ id: "a", timezone: "America/New_York" }, { id: "b", name: "B", timezone: "America/Denver" }] });
    assert.equal(p.get("resolveSiteTimeZone")({ attrs: { id: "b" } }).zone, "America/Denver");
    assert.equal(p.get("resolveSiteTimeZone")({ attrs: { dis: "B" } }).source, "NF Sites API");
    assert.equal(p.get("resolveSiteTimeZone")({ attrs: { id: "zzz" } }, { browser: false }).label, "UTC (fallback)", "two sites, no match: no guess");
  });
}
