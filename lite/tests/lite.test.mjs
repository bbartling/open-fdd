// node --test lite/tests — logic tests for Open-FDD Lite (no NF, no browser).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (rel) => readFileSync(path.join(root, rel), "utf8");
const manifest = JSON.parse(read("app.json"));
const require = createRequire(import.meta.url);
const hook = require(path.join(root, "hooks", "open_meteo_weather.js"));

const appSlug = (name) => (name.toLowerCase().match(/[a-z0-9]+/g) || []).join("-"); // same rule as nf_app_sync.app_slug

test("manifest: every file it lists exists, and every hook entry point is a listed file", () => {
  for (const [nfPath, rel] of Object.entries(manifest.files)) {
    assert.ok(nfPath.startsWith("/"), nfPath);
    assert.ok(existsSync(path.join(root, rel)), `missing ${rel}`);
  }
  for (const h of manifest.hooks) assert.ok(h.entryPoint in manifest.files, h.entryPoint);
});

test("manifest: every shipped file is listed (static/ and hooks/)", () => {
  const listed = new Set(Object.values(manifest.files));
  const walk = (dir) => readdirSync(path.join(root, dir), { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? walk(`${dir}/${e.name}`) : [`${dir}/${e.name}`]);
  for (const f of [...walk("static"), ...walk("hooks")]) assert.ok(listed.has(f), `${f} is not in app.json`);
});

test("Lite history views use shared range controls and keep overview samples bounded", () => {
  const charts = read("static/charts.js"), app = read("static/app.js"), page = read("static/chart-page.js");
  for (const key of ["lite.overview", "lite.chart", "lite.points"]) assert.ok(charts.includes(`key: "${key}"`) || app.includes(`"${key}"`));
  assert.match(app, /fetchRange\(list, range, \{ target: 72/);
  assert.match(app, /fetchRange\(\[p\], range/);
  assert.match(app, /read !== sparkRangeRead/);
  assert.match(app, /read !== pointHistoryRead/);
  assert.match(app, /renderRangeControl\(\$\("chartRange"\)/);
  assert.match(page, /renderRangeControl\(\$\("range"\)/);
  assert.doesNotMatch(app, /SPARK_HOURS/);
  assert.match(read("static/index.html"), /id="sparkRange"/);
  assert.match(read("static/index.html"), /id="histRange"/);
  assert.match(read("static/chart.html"), /id="range"/);
});

test("Lite chart range helpers encode URL state, resolve presets and chunk bounded NF history reads", async () => {
  const { createContext, runInContext } = await import("node:vm");
  const calls = [];
  const location = { href: "https://nf.example.test/chart.html?c=temps" };
  Object.defineProperty(location, "search", { get() { return new URL(this.href).search; } });
  const context = createContext({
    LT: { palette: [], axisLine: "", label: "", split: "", tipBg: "", tipText: "", legend: "", panel: "", filler: "", dark: false },
    URL, URLSearchParams, Intl, Date, Math, Object, Map, Set, Promise, Number, String, encodeURIComponent,
    location,
    history: { pushState(_s, _t, url) { location.href = String(url); }, replaceState(_s, _t, url) { location.href = String(url); } },
    esc: (s) => String(s),
    async api(url) {
      calls.push(url);
      return { data: [...new URL(url, "https://nf.example.test").searchParams.getAll("uuids")].map((uuid) => ({ uuid, values: [] })) };
    },
  });
  const api = runInContext(`${read("static/charts.js")}\n;({ getChartRangeState, setChartRangeState, resolveChartRange, dateTimeInputValue, dateTimeInputMs, chartTimeParts, chartTimeLabel, timeAxis, fetchRange })`, context);
  api.setChartRangeState("lite.chart", { preset: "custom", fromMs: 1000, toMs: 9000 });
  assert.deepEqual({
    preset: api.getChartRangeState("lite.chart").preset,
    fromMs: api.getChartRangeState("lite.chart").fromMs,
    toMs: api.getChartRangeState("lite.chart").toMs,
  }, { preset: "custom", fromMs: 1000, toMs: 9000 });
  assert.deepEqual(JSON.parse(JSON.stringify(api.resolveChartRange({ preset: "24h" }, { nowMs: 100000 }))), { fromMs: 100000 - 86400000, toMs: 100000 });
  assert.equal(api.dateTimeInputValue(Date.parse("2026-01-01T12:00:00Z"), "America/Chicago"), "2026-01-01T06:00");
  assert.ok(Number.isNaN(api.dateTimeInputMs("2026-03-08T02:30", "America/Chicago")), "reject nonexistent site wall time at DST spring transition");
  assert.equal(api.chartTimeParts(Date.parse("2026-01-01T12:00:00Z"), "America/Chicago").h, 6);
  assert.equal(api.timeAxis("America/Chicago").axisLabel.formatter(Date.parse("2026-01-01T12:00:00Z")), api.chartTimeLabel(Date.parse("2026-01-01T12:00:00Z"), "America/Chicago"));
  location.href = "https://nf.example.test/chart.html?range.lite.chart=custom&from.lite.chart=bad&to.lite.chart=9000";
  assert.equal(api.getChartRangeState("lite.chart").preset, "all", "malformed custom URL state normalizes to All");
  const points = Array.from({ length: 81 }, (_, i) => ({ uuid: `point-${i}` }));
  const range = await api.fetchRange(points, { preset: "custom", fromMs: Date.now() - 3600000, toMs: Date.now() }, { windowSec: 300 });
  assert.equal(range.series.size, 81);
  assert.equal(calls.length, 3);
  assert.ok(calls.every((url) => new URL(url, "https://nf.example.test").searchParams.getAll("uuids").length <= 40));
  assert.ok(calls.every((url) => /count=10000/.test(url) && /reverse=false/.test(url)));
});

test("manifest: the app id is the slug of the name (NF derives the id from the name)", () => {
  const { id, name } = manifest.application;
  assert.equal(name, "Open-FDD Lite");
  assert.equal(id, "open-fdd-lite");
  assert.equal(id, appSlug(name));
});

test("manifest: no FDD hook, no npm dependencies", () => {
  assert.deepEqual(manifest.hooks.map((h) => h.id), ["open-meteo-weather"]);
  assert.ok(!existsSync(path.join(root, "package.json")));
  assert.ok(!/require\((?!['"](https|http|node:)[^'"]*['"]\))/.test(read("hooks/open_meteo_weather.js")), "hook may only require node built-ins");
});

test("manifest: the weather hook config defaults to av.1-3 and matches the code", () => {
  const h = manifest.hooks[0];
  assert.deepEqual(h.config.avInstances, [1, 2, 3]);
  assert.deepEqual(hook.avInstances(h.config), [1, 2, 3]);
  assert.deepEqual(h.points.globalVariables.map((v) => v.label), ["oa_dry_bulb_web", "oa_rh_web", "oa_dewpoint_web"]);
});

test("renamed everywhere: no Bench Viz / bench-viz left in the shipped code, pages (the README keeps it for the migration note)", () => {
  const files = ["app.json", "hooks/open_meteo_weather.js",
    ...readdirSync(path.join(root, "static")).filter((f) => /\.(js|html|css)$/.test(f)).map((f) => `static/${f}`)];
  // `replaces` in app.json names the predecessor apps `install --remove-old` deletes: the one allowed mention
  const shipped = (f) => (f === "app.json" ? JSON.stringify({ ...manifest, replaces: undefined }) : read(f));
  for (const f of files) assert.ok(!/bench[ -_]?viz/i.test(shipped(f)), `${f} still says Bench Viz`);
  assert.deepEqual(manifest.replaces, ["bench-viz", "open-meteo-weather"]);
  for (const f of ["index.html", "chart.html", "tree.html"]) assert.match(read(`static/${f}`), /<title>Open-FDD Lite/);
  assert.match(read("hooks/open_meteo_weather.js"), /open-fdd-lite-weather-hook/);
});

test("no hard-coded site: no coordinates, city, device or bench names in the code", () => {
  const files = ["hooks/open_meteo_weather.js",
    ...readdirSync(path.join(root, "static")).filter((f) => /\.(js|html)$/.test(f)).map((f) => `static/${f}`)];
  for (const f of files) {
    const src = read(f);
    assert.ok(!/madison/i.test(src), `${f}: city name`);
    assert.ok(!/43\.07|89\.40/.test(src), `${f}: Madison coordinates`);
    assert.ok(!/\b-?\d{1,3}\.\d{4,}\b/.test(src), `${f}: a long decimal (lat/lon?)`);
    assert.ok(!/bens-?bench|FEC[- ]?5007|\b5007\b|bosspi|54545/i.test(src), `${f}: bench device/site name`);
    assert.ok(!/SITE_NAME|\bLATITUDE\b|\bLONGITUDE\b/.test(src), `${f}: hard-coded site constant`);
  }
});

test("hooks: the open-meteo URL is built from the coordinates it is given", () => {
  const url = hook.openMeteoUrl(12.5, -34.25);
  assert.match(url, /latitude=12\.5&longitude=-34\.25/);
  assert.match(url, /temperature_unit=fahrenheit/);
});

// ---- pickSite: same behaviour as the full edition's nf-app/hooks/weather.js ----------
const S = (id, latitude, longitude) => ({ id, name: id.toUpperCase(), latitude, longitude });

test("pickSite: the only site with coordinates is used", () => {
  const sites = [S("a", 10, 20), S("b", 0, 0), { id: "c" }];
  assert.equal(hook.pickSite(sites).id, "a");
});

test("pickSite: a 0,0 or missing location is not a location", () => {
  assert.throws(() => hook.pickSite([S("a", 0, 0), { id: "b" }]), /no NF site has latitude\/longitude/);
  assert.throws(() => hook.pickSite([]), /no NF site has latitude\/longitude/);
});

test("pickSite: several located sites need the config value `site`", () => {
  const sites = [S("a", 10, 20), S("b", 30, 40)];
  assert.throws(() => hook.pickSite(sites), /several NF sites.*"site"/);
  assert.equal(hook.pickSite(sites, "b").id, "b");
});

test("pickSite: a configured site must exist and have coordinates", () => {
  assert.throws(() => hook.pickSite([S("a", 10, 20)], "zzz"), /not an NF site/);
  assert.throws(() => hook.pickSite([S("a", 10, 20), S("b", 0, 0)], "b"), /no latitude\/longitude/);
});

test("pickSite: identical to nf-app/hooks/weather.js when that file is present", () => {
  const full = path.join(root, "..", "nf-app", "hooks", "weather.js");
  if (!existsSync(full)) return;
  const ref = require(full);
  const cases = [[[S("a", 10, 20)], undefined], [[S("a", 10, 20), S("b", 1, 2)], "b"], [[S("a", 0, 0)], undefined], [[S("a", 1, 2), S("b", 3, 4)], undefined]];
  for (const [sites, wanted] of cases) {
    const run = (fn) => { try { return fn(sites, wanted).id; } catch (e) { return `error: ${e.message}`; } };
    assert.equal(run(hook.pickSite), run(ref.pickSite));
  }
});

// ---- BACnet AV instances from config ----------------------------------------------------
test("avInstances: default 1-3; configurable as an array or a comma string", () => {
  assert.deepEqual(hook.avInstances(undefined), [1, 2, 3]);
  assert.deepEqual(hook.avInstances({}), [1, 2, 3]);
  assert.deepEqual(hook.avInstances({ avInstances: [101, 102, 103] }), [101, 102, 103]);
  assert.deepEqual(hook.avInstances({ avInstances: "7, 8, 9" }), [7, 8, 9]);
});

test("avInstances: rejects the wrong count, duplicates, negatives and non-integers", () => {
  for (const bad of [[1, 2], [1, 1, 2], [-1, 2, 3], [1.5, 2, 3], ["a", 2, 3], [1, 2, 4194303]]) {
    assert.throws(() => hook.avInstances({ avInstances: bad }), /avInstances/, JSON.stringify(bad));
  }
});

test("bacnetObjects: configured instances, names and units; the site name is only in the description", () => {
  const objs = hook.bacnetObjects("Some Site", [10, 11, 12]);
  assert.deepEqual(objs.map((o) => o.instance), [10, 11, 12]);
  assert.deepEqual(objs.map((o) => o.label), ["oa_dry_bulb_web", "oa_rh_web", "oa_dewpoint_web"]);
  assert.deepEqual(objs.map((o) => o.units), [64, 29, 64]);
  assert.ok(objs.every((o) => o.description.includes("Some Site")));
});

// ---- the hook end to end against a fake sdk.http ------------------------------------------
test("hook run: location from NF /sites, AVs created at the configured instances", async () => {
  const calls = [];
  const posted = [];
  const sdk = {
    logEvent() {},
    http: {
      get: async (url) => {
        calls.push(`GET ${url}`);
        if (url.startsWith("/api/v1/sites")) return { data: { sites: [{ id: "s1", name: "Site One", latitude: 40.5, longitude: -75.25 }] } };
        if (url === "/api/v1/bacnet/local") return { data: { objects: [] } };
        throw new Error(`unexpected GET ${url}`);
      },
      post: async (url, body) => {
        calls.push(`POST ${url}`);
        posted.push([url, body]);
        return { data: { success: true } };
      },
      patch: async () => ({ data: {} }),
    },
  };
  // Stand in for Open-Meteo: intercept the https module the hook captured at load time.
  const https = require("https");
  const realGet = https.get;
  let requested = "";
  https.get = (url, opts, cb) => {
    requested = url;
    const { EventEmitter } = require("events");
    const res = new EventEmitter();
    res.statusCode = 200;
    res.setEncoding = () => {};
    const req = new EventEmitter();
    req.setTimeout = () => {};
    req.destroy = () => {};
    setImmediate(() => {
      cb(res);
      res.emit("data", JSON.stringify({ current: { time: "2026-01-01T00:00", temperature_2m: 50, relative_humidity_2m: 60, dew_point_2m: 36.3 } }));
      res.emit("end");
    });
    return req;
  };
  try {
    const vars = { byLabel: (label) => ({ uuid: `u-${label}` }) };
    const out = await hook({ globalVariables: vars, sdk, config: { avInstances: [21, 22, 23] } });
    assert.match(requested, /latitude=40\.5&longitude=-75\.25/);
    assert.equal(out.site, "s1");
    assert.deepEqual(Object.keys(out.bacnet), ["av.21", "av.22", "av.23"]);
    const created = posted.filter(([u]) => u === "/api/v1/bacnet/local").map(([, b]) => b.objectId.instance);
    assert.deepEqual(created, [21, 22, 23]);
    assert.equal(posted.filter(([u]) => u === "/api/v1/point/data").length, 3);
  } finally {
    https.get = realGet;
  }
});

// ---- ECharts 6 ----------------------------------------------------------------------------
test("vendored ECharts is 6.1.0 and still builds the chart types Lite uses", () => {
  const echarts = require(path.join(root, "static", "vendor", "echarts.min.js"));
  assert.equal(echarts.version, "6.1.0");
  const chart = echarts.init(null, null, { renderer: "svg", ssr: true, width: 400, height: 300 });
  const axis = { axisLine: { lineStyle: { color: "#2563eb" } }, axisLabel: { color: "#475569" }, splitLine: { lineStyle: { color: "#e2e8f0" } } };
  const time = [Date.UTC(2026, 0, 1), Date.UTC(2026, 0, 2)];
  chart.setOption({
    tooltip: { trigger: "axis", backgroundColor: "#fff", borderColor: "#2563eb", textStyle: { color: "#000" } },
    legend: { top: 0 }, grid: { left: 50, right: 50, top: 36, bottom: 60 },
    xAxis: { type: "time", ...axis }, yAxis: [{ type: "value", scale: true, ...axis }, { type: "value", position: "right", ...axis }],
    dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }],
    series: [
      { type: "line", showSymbol: false, data: [[time[0], 1], [time[1], 2]], areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: "#4cc9f0" }, { offset: 1, color: "#fff" }]) } },
      { type: "line", yAxisIndex: 1, step: "end", data: [[time[0], 0], [time[1], 1]] },
    ],
  }, true);
  assert.ok(chart.renderToSVGString().includes("<svg"));
  chart.dispose();

  const heat = echarts.init(null, null, { renderer: "svg", ssr: true, width: 400, height: 300 });
  heat.setOption({
    xAxis: { type: "category", data: ["a", "b"] }, yAxis: { type: "category", data: ["d1", "d2"] },
    visualMap: { min: 0, max: 10, calculable: true, orient: "horizontal", inRange: { color: ["#3a0ca3", "#f94144"] } },
    series: [{ type: "heatmap", data: [[0, 0, 1], [1, 1, 9]], itemStyle: { borderColor: "#fff", borderWidth: 2, borderRadius: 3 } }],
  });
  assert.ok(heat.renderToSVGString().includes("<svg"));
  heat.dispose();

  const box = echarts.init(null, null, { renderer: "svg", ssr: true, width: 400, height: 300 });
  box.setOption({ xAxis: { type: "category", data: ["d1"] }, yAxis: { type: "value" }, series: [{ type: "candlestick", data: [[1, 2, 0, 3]] }, { type: "scatter", data: [[0, 1]] }, { type: "bar", data: [1] }] });
  assert.ok(box.renderToSVGString().includes("<svg"));
  box.dispose();

  const tree = echarts.init(null, null, { renderer: "svg", ssr: true, width: 400, height: 300 });
  tree.setOption({ series: [{ type: "tree", data: [{ name: "site", children: [{ name: "equip" }] }], orient: "LR", symbolSize: 9, initialTreeDepth: 3, expandAndCollapse: true, roam: true }] });
  assert.ok(tree.renderToSVGString().includes("<svg"));
  tree.dispose();
});

test("pages load the vendored UMD build and the Lite theme scripts in the right order", () => {
  for (const f of ["index.html", "chart.html", "tree.html"]) {
    const html = read(`static/${f}`);
    const at = (s) => html.indexOf(s);
    assert.ok(at('src="theme-init.js"') > 0 && at('src="theme-init.js"') < at('src="lite-theme.js"'), `${f}: theme order`);
    assert.ok(at('src="lite-theme.js"') < at('src="vendor/echarts.min.js"'), `${f}: LT before echarts`);
    if (f !== "tree.html") assert.ok(at('src="lite-theme.js"') < at('src="charts.js"'), `${f}: LT before charts.js`);
    assert.ok(html.includes("ECharts 6.1.0"), `${f}: comment`);
  }
});

// ---- strict CSP + RDF export (Lite parity with the full edition) ----------------------
const pages = ["index.html", "chart.html", "tree.html"];

test("CSP meta on every page: self-only styles, no eval, https: scripts only for clerk-js", () => {
  for (const f of pages) {
    const html = read(`static/${f}`);
    const m = html.match(/<meta http-equiv="Content-Security-Policy" content="([^"]+)"/);
    assert.ok(m, `${f}: CSP meta missing`);
    const csp = m[1];
    assert.match(csp, /style-src 'self'(;|$)/, f);
    assert.match(csp, /script-src 'self' https:(;|$)/, f);
    assert.ok(!/unsafe-inline|unsafe-eval|wasm-unsafe-eval/.test(csp), `${f}: ${csp}`);
    assert.match(csp, /object-src 'none'/, f);
    assert.ok(html.indexOf("Content-Security-Policy") < html.indexOf("<script"), `${f}: CSP must precede scripts`);
  }
  assert.match(read("static/nf.js"), /clerk-js@\$\{CLERK_JS_VERSION\}/); // the reason for https: in script-src
});

test("no inline style=, event handlers, javascript: URLs, eval or new Function in Lite static files", () => {
  const files = readdirSync(path.join(root, "static")).filter((f) => /\.(html|js)$/.test(f));
  for (const f of files) {
    const src = read(`static/${f}`).replace(/<!--[\s\S]*?-->/g, "").replace(/\/\*[\s\S]*?\*\/|^\s*\/\/.*$/gm, "");
    assert.ok(!/\sstyle\s*=/.test(src), `${f}: inline style=`);
    assert.ok(!/\son[a-z]+\s*=\s*["']/.test(src), `${f}: inline event handler`);
    assert.ok(!/javascript:/.test(src), `${f}: javascript: URL`);
    assert.ok(!/\beval\s*\(|new Function\b/.test(src), `${f}: eval / new Function`);
  }
  for (const f of pages) assert.ok(!/<script>/.test(read(`static/${f}`)), `${f}: inline script`);
});

async function liteTurtle() {
  const { createContext, runInContext } = await import("node:vm");
  const ctx = createContext({ console, URLSearchParams, TextDecoder, atob, btoa });
  for (const f of ["nf.js", "model.js"]) runInContext(read(`static/${f}`), ctx, { filename: f });
  const repo = path.resolve(root, "..");
  ctx.records = JSON.parse(readFileSync(path.join(repo, "tools/rdf-check/fixtures/model.json"), "utf8")).records;
  const pt = ctx.records.find((x) => x.pointType === "POINT");
  pt.attrs = { ...pt.attrs, class: "discharge-air-temp-sensor" }; // the fixture has no NF class
  return runInContext(`(() => {
    const of = (t) => records.filter((x) => x.pointType === t);
    const model = { sites: of("SITE"), equips: of("EQUIPMENT"), devices: of("DEVICE"), points: of("POINT").map(toPoint) };
    return modelToTurtle(model, "urn:test:", { nfBase: "http://nf.example.test" });
  })()`, ctx);
}

test("Turtle export: Brick time-series refs, schema:url, nfClass property, every term defined", async () => {
  const { turtle } = await liteTurtle();
  assert.match(turtle, /@prefix ref: <https:\/\/brickschema.org\/schema\/Brick\/ref#>/);
  assert.match(turtle, /ref:hasExternalReference \[ a ref:TimeseriesReference/);
  assert.match(turtle, /ref:hasTimeseriesId "/);
  assert.match(turtle, /schema:url <http:\/\/nf.example.test\/api\/v1\/point\/data\?uuids=/);
  assert.match(turtle, /local:store_nf\n\s+a ref:Database/);
  assert.match(turtle, /local:nfClass "/);
  assert.match(turtle, /local:nfClass\n\s+a rdf:Property/);
});

test("Turtle export passes the Oxigraph + rdflib checker (tools/rdf-check/check_ttl.py)", async (t) => {
  const { spawnSync } = await import("node:child_process");
  const { mkdtempSync, writeFileSync } = await import("node:fs");
  const { tmpdir } = await import("node:os");
  const py = ["python", "python3"].find((p) => spawnSync(p, ["-c", "import pyoxigraph, rdflib"]).status === 0);
  if (!py) return t.skip("python with pyoxigraph + rdflib not available");
  const file = path.join(mkdtempSync(path.join(tmpdir(), "lite-ttl-")), "lite.ttl");
  writeFileSync(file, (await liteTurtle()).turtle);
  const r = spawnSync(py, [path.resolve(root, "..", "tools/rdf-check/check_ttl.py"), file], { encoding: "utf8" });
  assert.equal(r.status, 0, r.stdout + r.stderr);
});
