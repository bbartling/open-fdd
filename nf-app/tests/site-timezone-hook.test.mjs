// node --test nf-app/tests/site-timezone-hook.test.mjs
// #1587: the hooks' site time zone resolver (hooks/lib/site-timezone.js, shared/hooks/site-timezone.js) must give the
// same zone and source as the dashboard's resolveSiteTimeZone (static/charts.js). charts.js is a browser global script,
// so the two cannot be one file: this runs both over the same cases.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const require = createRequire(import.meta.url);
const tz = require("../hooks/lib/site-timezone.js");
const chartsSrc = readFileSync(new URL("../static/charts.js", import.meta.url), "utf8");

function ui(browserZone = "UTC") {
  const DTF = function (l, o) { return l === undefined && o === undefined ? { resolvedOptions: () => ({ timeZone: browserZone }) } : new Intl.DateTimeFormat(l, o); };
  const ctx = vm.createContext({ URL, URLSearchParams, Date, Math, Object, Number, String, Map, Set, Promise, Array, JSON,
    Intl: { ...Intl, DateTimeFormat: Object.assign(DTF, { supportedLocalesOf: Intl.DateTimeFormat.supportedLocalesOf }) },
    LT: {}, location: { pathname: "/", href: "https://x/", search: "" }, esc: (s) => String(s ?? ""), api: async () => ({}) });
  vm.runInContext(chartsSrc, ctx);
  return ctx;
}

const site = (attrs = {}, name = "site-a") => ({ uuid: "s", name, pointType: "SITE", attrs: { id: name, ...attrs } });
const CASES = [
  ["model tz", site({ tz: "America/Chicago" }), { config: { timezone: "America/Denver" }, sites: [{ id: "site-a", timezone: "Asia/Tokyo" }] }],
  ["model timezone attr", site({ timezone: "Europe/Berlin" }), { config: {}, sites: [] }],
  ["invalid model tz falls through to option", site({ tz: "Nope/Zone" }), { config: { timezone: "America/Denver" }, sites: [] }],
  ["option beats NF Sites", site(), { config: { timezone: "America/Denver" }, sites: [{ id: "site-a", timezone: "Asia/Tokyo" }] }],
  ["NF Sites by id", site(), { config: {}, sites: [{ id: "x", timezone: "Asia/Seoul" }, { id: "site-a", timezone: "Asia/Tokyo" }] }],
  ["NF Sites sole site", site(), { config: {}, sites: [{ id: "other", timezone: "Asia/Tokyo" }] }],
  ["NF Sites two others: none", site(), { config: {}, sites: [{ id: "x", timezone: "Asia/Seoul" }, { id: "y", timezone: "Asia/Tokyo" }] }],
  ["invalid option ignored", site(), { config: { timezone: "Mars/Olympus" }, sites: [] }],
  ["nothing at all", site(), { config: {}, sites: [] }],
  ["no site record", null, { config: { timezone: "America/Chicago" }, sites: [] }],
];

for (const [name, rec, inputs] of CASES) {
  test(`hook resolver == dashboard resolver: ${name}`, () => {
    const g = ui("UTC");
    g.setSiteTimeZoneSources({ appOption: inputs.config.timezone, sites: inputs.sites.filter((s) => tz.knownZone(s.timezone)) });
    const want = g.resolveSiteTimeZone(rec, { browser: false, register: false });
    const got = tz.resolveSiteTimeZone(rec, { ...inputs, host: null });
    assert.equal(got.zone, want.zone);
    assert.equal(got.source, want.source);
    assert.equal(got.fallback, want.fallback);
  });
}

test("host zone is the fourth step; a UTC host tells nothing", () => {
  assert.deepEqual(tz.resolveSiteTimeZone(site(), { host: "America/Chicago" }), { zone: "America/Chicago", source: "host", fallback: true, label: "America/Chicago (host fallback)" });
  for (const utc of ["UTC", "Etc/UTC", "GMT", null]) {
    const r = tz.resolveSiteTimeZone(site(), { host: utc });
    assert.deepEqual([r.zone, r.source, r.fallback], ["UTC", "none", true]);
  }
});

test("an invalid option is reported in `ignored`, a blank one is simply unset", () => {
  assert.match(tz.resolveSiteTimeZone(site(), { config: { timezone: "Mars/Olympus" }, host: null }).ignored, /Mars\/Olympus/);
  assert.equal(tz.resolveSiteTimeZone(site(), { config: { timezone: "  " }, host: null }).ignored, undefined);
});

test("loadNfSites keeps sites with a usable zone; a failing API leaves the source empty and names the error", async () => {
  const ok = await tz.loadNfSites({ get: async () => ({ data: { sites: [{ id: "a", timezone: "Asia/Tokyo" }, { id: "b" }, { id: "c", timezone: "bad" }], totalCount: 3 } }) });
  assert.deepEqual(ok.sites.map((s) => s.id), ["a"]);
  const bad = await tz.loadNfSites({ get: async () => { throw new Error("HTTP 500"); } });
  assert.deepEqual(bad.sites, []);
  assert.match(bad.error, /500/);
});

test("analytics hook: the sandboxed dashboard code gets the app option and NF Sites zones (weekly runtime in site-local time)", () => {
  const analytics = require("../hooks/analytics.js");
  const g = analytics.loadSandbox({ get: async () => ({ data: {} }) }, Date.now(), { appOption: "America/Chicago", sites: [] });
  const r = g("resolveSiteTimeZone")(site(), { browser: false, register: false });
  assert.deepEqual([r.zone, r.source], ["America/Chicago", "app option"]);
  const none = analytics.loadSandbox({ get: async () => ({ data: {} }) }, Date.now());
  assert.equal(none("resolveSiteTimeZone")(site(), { browser: false, register: false }).source, "none");
});
