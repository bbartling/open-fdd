import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);

function loadSharedUi(opts = {}) {
  const storage = new Map(Object.entries(opts.storage || {}));
  const ctx = {
    console,
    Date,
    Math,
    Number,
    String,
    Array,
    Object,
    Map,
    Set,
    JSON,
    Intl,
    URLSearchParams,
    RegExp,
    localStorage: {
      getItem: (k) => (storage.has(k) ? storage.get(k) : null),
      setItem: (k, v) => storage.set(k, String(v)),
      removeItem: (k) => storage.delete(k),
    },
    ofddUnits: require("../static/units.js"),
    api: async () => ({}),
    fetch: async () => ({ ok: false }),
    location: { host: "test-box", pathname: "/api/v1/apps/static/open-fdd/", hash: "" },
    weatherDisabled: () => !!opts.weatherDisabled,
  };
  vm.createContext(ctx);
  const noop = () => {};
  const fakeEl = () => ({ innerHTML: "", textContent: "", hidden: false, disabled: false, value: "", style: {}, classList: { toggle: noop, add: noop, remove: noop }, setAttribute: noop, append: noop, prepend: noop, querySelectorAll: () => [], addEventListener: noop });
  ctx.document = { getElementById: fakeEl, querySelectorAll: () => [], createElement: fakeEl, hidden: false, addEventListener: noop };
  ctx.window = { history: { replaceState: noop }, addEventListener: noop };
  ctx.ofddTabs = {};
  ctx.ofddEquipScoped = new Set();
  ctx.ofddWire = [];
  ctx.ofddOnTheme = [];
  ctx.setTimeout = noop;
  ctx.setInterval = noop;
  ctx.renderRangeControl = noop;
  ctx.resolveChartSelection = async () => ({ resolvedBounds: { fromMs: 0, toMs: 1 } });
  ctx.getChartRangeState = () => ({ preset: "24h" });
  ctx.resolveSiteTimeZone = () => ({ zone: "UTC" });
  ctx.onThemeChange = noop;
  ctx.streamUpdates = () => noop;
  for (const f of ["model.js", "charts.js", "app-core.js"]) {
    const code = fs.readFileSync(path.join(fileURLToPath(new URL("../../shared/static", import.meta.url)), f), "utf8");
    vm.runInContext(code, ctx, { filename: f });
  }
  return { ctx, storage };
}

const mkPoint = (uuid, {
  siteRef = "site-a",
  equipRef = "",
  deviceRef = "",
  weatherStationRef = "",
  tags = ["point", "sensor", "his"],
  kind = "Number",
  units = "°C",
  cls = "",
  dis = uuid,
  name = uuid,
  latest = null,
} = {}) => ({
  uuid,
  siteRef,
  equipRef,
  deviceRef,
  weatherStationRef,
  tags,
  kind,
  units,
  cls,
  dis,
  name,
  latest,
  rec: { uuid, name, pointType: kind, attrs: { dis, siteRef, equipRef, deviceRef, weatherStationRef, units, class: cls } },
});

const mkEquip = (id, { siteRef = "site-a", dis = id, markers = ["equip"], attrs = {} } = {}) => ({
  name: id,
  attrs: { id, siteRef, dis, markers: markers.join(","), ...attrs },
});

test("normalizeTempToC converts C, F, K and rejects missing/invalid units", () => {
  const { ctx } = loadSharedUi();
  assert.equal(ctx.normalizeTempToC(20, "°C"), 20);
  assert.equal(ctx.normalizeTempToC(20, "degC"), 20);
  assert.ok(Math.abs(ctx.normalizeTempToC(50, "°F") - 10) < 1e-9);
  assert.ok(Math.abs(ctx.normalizeTempToC(293.15, "K") - 20) < 1e-9);
  assert.equal(ctx.normalizeTempToC(70, ""), null);
  assert.equal(ctx.normalizeTempToC(NaN, "°C"), null);
  assert.equal(ctx.normalizeTempToC("70", "°F"), null);
});

test("resolveOverviewOatC prefers fresh local BAS OAT over weather and rejects stale/ambiguous/untyped", () => {
  const { ctx } = loadSharedUi();
  const now = Date.UTC(2026, 10, 13, 18, 0, 0);
  const freshTs = new Date(now - 5 * 60e3).toISOString();
  const staleTs = new Date(now - 90 * 60e3).toISOString();
  const equips = [mkEquip("ahu-1", { markers: ["equip", "ahu"] })];
  const basOat = mkPoint("oat-bas", {
    equipRef: "ahu-1",
    tags: ["point", "outside", "air", "temp", "sensor", "his"],
    units: "°F",
    latest: { ts: freshTs, double: 50 },
  });
  const wxOat = mkPoint("oat-wx", {
    weatherStationRef: "wx-1",
    tags: ["point", "weather", "outside", "air", "temp", "sensor", "his"],
    units: "°C",
    latest: { ts: freshTs, double: 14 },
  });
  const res1 = ctx.resolveOverviewOatC({ equips, points: [basOat, wxOat] }, "site-a", { nowMs: now });
  assert.equal(res1.source, "local");
  assert.ok(Math.abs(res1.tempC - 10) < 1e-9);
  assert.equal(res1.disagree, undefined);

  // Stale local BAS OAT falls back explicitly to valid weather OAT
  const staleBas = { ...basOat, latest: { ts: staleTs, double: 30 } };
  const res2 = ctx.resolveOverviewOatC({ equips, points: [staleBas, wxOat] }, "site-a", { nowMs: now });
  assert.equal(res2.source, "weather");
  assert.equal(res2.tempC, 14);

  // Untyped local OAT falls back to weather
  const untypedBas = { ...basOat, units: "" };
  const res3 = ctx.resolveOverviewOatC({ equips, points: [untypedBas, wxOat] }, "site-a", { nowMs: now });
  assert.equal(res3.source, "weather");

  // Ambiguous local OAT (two distinct fresh sensors) falls back to weather
  const basOat2 = { ...basOat, uuid: "oat-bas-2", latest: { ts: freshTs, double: 55 } };
  const res4 = ctx.resolveOverviewOatC({ equips, points: [basOat, basOat2, wxOat] }, "site-a", { nowMs: now });
  assert.equal(res4.source, "weather");
});

// #1774: the picker's OAT, its band and its reason are shown in the display units; the pick stays in SI.
const oatPickerModel = (now, { localC = null, weatherC = null } = {}) => {
  const freshTs = new Date(now - 2 * 60e3).toISOString();
  const points = [];
  if (localC != null) {
    points.push(mkPoint("oat-bas", {
      equipRef: "rtu-1", dis: "RTU 1 OAT", tags: ["point", "outside", "air", "temp", "sensor", "his"],
      units: "°C", latest: { ts: freshTs, double: localC },
    }));
  }
  if (weatherC != null) {
    points.push(mkPoint("oat-wx", {
      weatherStationRef: "wx-1", tags: ["point", "weather", "outside", "air", "temp", "his"],
      units: "°C", latest: { ts: freshTs, double: weatherC },
    }));
  }
  return {
    equips: [
      mkEquip("ahu-1", { dis: "AHU 1", markers: ["equip", "ahu"] }),
      mkEquip("rtu-1", { dis: "RTU 1", markers: ["equip", "rtu"] }),
      mkEquip("blr-1", { dis: "Boiler 1", markers: ["equip", "boiler"] }),
    ],
    points,
  };
};

test("autoSelectOverviewEquip reason and band follow the imperial display units (default)", () => {
  const { ctx } = loadSharedUi();
  const now = Date.UTC(2026, 10, 13, 18, 0, 0);
  const auto = ctx.autoSelectOverviewEquip(oatPickerModel(now, { weatherC: 23.3 }), "site-a", { nowMs: now });
  assert.equal(auto.equipId, "rtu-1");
  assert.equal(auto.reason, "Auto-selected RTU 1 (RTU; OAT 73.9 °F from site weather)");
  assert.equal(auto.band, "53.6 °F to < 75.2 °F");
  assert.equal(auto.oat.tempC, 23.3);
  assert.doesNotMatch(auto.reason, /°C/);

  const cold = ctx.autoSelectOverviewEquip(oatPickerModel(now, { weatherC: 1.3 }), "site-a", { nowMs: now });
  assert.equal(cold.equipId, "blr-1");
  assert.equal(cold.band, "< 53.6 °F");
  assert.match(cold.reason, /OAT 34\.3 °F from site weather/);

  const hot = ctx.autoSelectOverviewEquip(oatPickerModel(now, { weatherC: 30 }), "site-a", { nowMs: now });
  assert.equal(hot.equipId, "rtu-1");
  assert.equal(hot.band, ">= 75.2 °F");
  assert.equal(hot.reason, "Auto-selected RTU 1 (no chiller/chilled-water for OAT 86.0 °F from site weather; fallback RTU)");
});

test("autoSelectOverviewEquip reason and band follow the SI display units when chosen", () => {
  const { ctx } = loadSharedUi();
  ctx.ofddUnits = { ...ctx.ofddUnits, displaySystem: () => "si" };
  const now = Date.UTC(2026, 10, 13, 18, 0, 0);
  const auto = ctx.autoSelectOverviewEquip(oatPickerModel(now, { weatherC: 23.3 }), "site-a", { nowMs: now });
  assert.equal(auto.reason, "Auto-selected RTU 1 (RTU; OAT 23.3 °C from site weather)");
  assert.equal(auto.band, "12.0 °C to < 24.0 °C");
});

test("autoSelectOverviewEquip without units.js (Lite) shows imperial", () => {
  const { ctx } = loadSharedUi();
  delete ctx.ofddUnits;
  const now = Date.UTC(2026, 10, 13, 18, 0, 0);
  const auto = ctx.autoSelectOverviewEquip(oatPickerModel(now, { weatherC: 23.3 }), "site-a", { nowMs: now });
  assert.equal(auto.reason, "Auto-selected RTU 1 (RTU; OAT 73.9 °F from site weather)");
  assert.equal(auto.band, "53.6 °F to < 75.2 °F");
  const bad = ctx.autoSelectOverviewEquip(oatPickerModel(now, { localC: 23.3, weatherC: 1.3 }), "site-a", { nowMs: now });
  assert.match(bad.reason, /local BAS OAT 73\.9 °F ignored: differs from site weather by more than 18 Δ°F\)$/);
});

test("Overview OAT: a local BAS OAT that disagrees with site weather is not trusted (#1774)", () => {
  const { ctx } = loadSharedUi();
  const now = Date.UTC(2026, 10, 13, 18, 0, 0);
  // The issue's case: an indoor or mis-tagged "OAT" reads 23.3 °C while web weather says 1.3 °C.
  const model = oatPickerModel(now, { localC: 23.3, weatherC: 1.3 });
  const oat = ctx.resolveOverviewOatC(model, "site-a", { nowMs: now });
  assert.equal(oat.source, "weather");
  assert.equal(oat.tempC, 1.3);
  assert.ok(Math.abs(oat.disagree.deltaK - 22) < 1e-9);
  assert.equal(oat.disagree.localC, 23.3);
  assert.equal(oat.disagree.maxK, 10);

  const auto = ctx.autoSelectOverviewEquip(model, "site-a", { nowMs: now });
  assert.equal(auto.equipId, "blr-1");
  assert.equal(auto.reason, "Auto-selected Boiler 1 (boiler/heating-water; OAT 34.3 °F from site weather; "
    + "local BAS OAT 73.9 °F ignored: differs from site weather by more than 18 Δ°F)");

  // Within the delta the local sensor is still preferred.
  const close = ctx.resolveOverviewOatC(oatPickerModel(now, { localC: 8, weatherC: 1.3 }), "site-a", { nowMs: now });
  assert.equal(close.source, "local");
  assert.equal(close.disagree, undefined);

  // The delta is configurable.
  const strict = ctx.resolveOverviewOatC(oatPickerModel(now, { localC: 8, weatherC: 1.3 }), "site-a", { nowMs: now, maxOatDisagreeK: 5 });
  assert.equal(strict.source, "weather");

  // No usable weather (disabled or missing): the local sensor is all there is, so it is used.
  const noWx = ctx.resolveOverviewOatC(oatPickerModel(now, { localC: 23.3 }), "site-a", { nowMs: now });
  assert.equal(noWx.source, "local");
  const wxOff = ctx.resolveOverviewOatC(model, "site-a", { nowMs: now, weatherOff: true });
  assert.equal(wxOff.source, "local");
});

test("autoSelectOverviewEquip follows <12 C boiler, 12-24 C RTU, >=24 C chiller bands and deterministic fallbacks", () => {
  const { ctx } = loadSharedUi();
  const now = Date.UTC(2026, 10, 13, 18, 0, 0);
  const freshTs = new Date(now - 2 * 60e3).toISOString();
  const equips = [
    mkEquip("ch-1", { dis: "Chiller 1", markers: ["equip", "chiller", "system"] }),
    mkEquip("rtu-1", { dis: "RTU 1", markers: ["equip", "rtu"] }),
    mkEquip("blr-1", { dis: "Boiler 1", markers: ["equip", "boiler", "plant"] }),
  ];
  const makeModel = (tempC) => ({
    equips,
    points: [mkPoint("wx-oat", {
      weatherStationRef: "wx-1",
      tags: ["point", "weather", "outside", "air", "temp", "his"],
      units: "°C",
      latest: { ts: freshTs, double: tempC },
    })],
  });

  // Cold (< 12 C) -> boiler
  assert.equal(ctx.autoSelectOverviewEquip(makeModel(11.9), "site-a", { nowMs: now }).equipId, "blr-1");
  // Exact boundary 12.0 C -> RTU
  assert.equal(ctx.autoSelectOverviewEquip(makeModel(12.0), "site-a", { nowMs: now }).equipId, "rtu-1");
  // Exact boundary 24.0 C -> chiller
  assert.equal(ctx.autoSelectOverviewEquip(makeModel(24.0), "site-a", { nowMs: now }).equipId, "ch-1");

  // Missing preferred chiller in hot weather -> falls back to RTU/AHU
  const noChiller = { equips: [equips[1], equips[2]], points: makeModel(30).points };
  assert.equal(ctx.autoSelectOverviewEquip(noChiller, "site-a", { nowMs: now }).equipId, "rtu-1");

  // Missing OAT -> deterministic RTU/AHU fallback
  const noOat = { equips, points: [] };
  assert.equal(ctx.autoSelectOverviewEquip(noOat, "site-a", { nowMs: now }).equipId, "rtu-1");

  // Empty site -> empty state
  assert.equal(ctx.autoSelectOverviewEquip({ equips: [], points: [] }, "site-a", { nowMs: now }).equipId, "");
});

test("resolveOverviewSelection isolates manual choices per exact site ID and preserves choice across live refresh", () => {
  const { ctx } = loadSharedUi();
  const now = Date.UTC(2026, 10, 13, 18, 0, 0);
  const freshTs = new Date(now - 60e3).toISOString();
  const model = {
    equips: [
      mkEquip("ahu-1", { siteRef: "site-a", dis: "AHU 1", markers: ["equip", "ahu"] }),
      mkEquip("blr-1", { siteRef: "site-a", dis: "Boiler 1", markers: ["equip", "boiler"] }),
      mkEquip("ahu-1", { siteRef: "site-b", dis: "AHU 1 (B)", markers: ["equip", "ahu"] }),
      mkEquip("ch-1", { siteRef: "site-b", dis: "Chiller 1 (B)", markers: ["equip", "chiller"] }),
    ],
    points: [
      mkPoint("oat-a", { siteRef: "site-a", weatherStationRef: "wx-a", tags: ["point", "weather", "outside", "air", "temp", "his"], units: "°C", latest: { ts: freshTs, double: 5 } }),
      mkPoint("oat-b", { siteRef: "site-b", weatherStationRef: "wx-b", tags: ["point", "weather", "outside", "air", "temp", "his"], units: "°C", latest: { ts: freshTs, double: 30 } }),
    ],
  };

  ctx.saveOverviewEquipForSite("site-a", "ahu-1");
  const selA = ctx.resolveOverviewSelection(model, "site-a", { nowMs: now });
  assert.equal(selA.equipId, "ahu-1");
  assert.equal(selA.mode, "manual");

  // Site B has no saved choice even though it also has an equip named "ahu-1"
  const selB = ctx.resolveOverviewSelection(model, "site-b", { nowMs: now });
  assert.equal(selB.equipId, "ch-1");
  assert.equal(selB.mode, "auto");

  // forceAuto resets manual choice on site-a back to weather-based selection (blr-1 at 5 C)
  const resetA = ctx.resolveOverviewSelection(model, "site-a", { nowMs: now, forceAuto: true });
  assert.equal(resetA.equipId, "blr-1");
  assert.equal(resetA.mode, "auto");
});

test("scopedEquipmentInventory includes all modeled I/O, preserves zero/false, isolates same-site, excludes FDD & ambiguous deviceRef", () => {
  const { ctx } = loadSharedUi();
  const now = Date.UTC(2026, 10, 13, 18, 0, 0);
  const freshTs = new Date(now - 60e3).toISOString();
  const model = {
    equips: [
      mkEquip("rtu-1", { siteRef: "site-a", dis: "RTU 1", markers: ["equip", "rtu"] }),
      mkEquip("rtu-2", { siteRef: "site-a", dis: "RTU 2", markers: ["equip", "rtu"] }),
    ],
    devices: [
      { name: "dev-1", attrs: { id: "dev-1", siteRef: "site-a", equipRef: "rtu-1" } },
      { name: "dev-shared", attrs: { id: "dev-shared", siteRef: "site-a" } },
    ],
    points: [
      mkPoint("p-temp", { equipRef: "rtu-1", tags: ["point", "temp", "sensor", "his"], units: "°C", cls: "SupplyAirTemperatureSensor", dis: "SAT", latest: { ts: freshTs, double: 0 } }),
      mkPoint("p-sp", { equipRef: "rtu-1", tags: ["point", "temp", "sp", "his"], units: "°C", dis: "SAT Sp", latest: { ts: freshTs, double: 13 } }),
      mkPoint("p-cmd", { equipRef: "rtu-1", tags: ["point", "damper_position", "cmd"], units: "%", dis: "OA Damper Cmd", latest: { ts: freshTs, double: 25 } }),
      mkPoint("p-bool", { equipRef: "rtu-1", tags: ["point", "fan", "sensor", "his"], kind: "Bool", units: "", dis: "Fan Status", latest: { ts: freshTs, boolean: false } }),
      mkPoint("p-enum", { equipRef: "rtu-1", tags: ["point", "mode", "sensor", "his"], kind: "Enum", units: "", dis: "Unit Mode", latest: { ts: freshTs, enumerated: 2 } }),
      mkPoint("p-text", { equipRef: "rtu-1", tags: ["point", "alarm", "sensor"], kind: "Str", units: "", dis: "Alarm Text", latest: { ts: freshTs, characterString: "Normal" } }),
      mkPoint("p-dev-unambig", { equipRef: "", deviceRef: "dev-1", tags: ["point", "sensor"], kind: "Number", units: "Pa", dis: "Static", latest: { ts: freshTs, double: 250 } }),
      // Shared controller linked to both rtu-1 and rtu-2 -> ambiguous, must stay out of unlinked deviceRef match
      mkPoint("p-dev-shared-1", { equipRef: "rtu-1", deviceRef: "dev-shared", tags: ["point", "sensor"], dis: "Shared 1" }),
      mkPoint("p-dev-shared-2", { equipRef: "rtu-2", deviceRef: "dev-shared", tags: ["point", "sensor"], dis: "Shared 2" }),
      mkPoint("p-dev-ambig", { equipRef: "", deviceRef: "dev-shared", tags: ["point", "sensor"], dis: "Ambiguous" }),
      // Wrong site point with same equipRef -> gap, excluded from ioPoints
      mkPoint("p-wrong-site", { siteRef: "site-b", equipRef: "rtu-1", tags: ["point", "temp", "sensor"], dis: "Wrong Site" }),
      // FDD output -> kept in fddPoints, not ioPoints
      mkPoint("p-fdd", { equipRef: "rtu-1", tags: ["point", "fdd", "fault", "his"], dis: "FC1 Fault", latest: { ts: freshTs, double: 0 } }),
    ],
  };

  const inv = ctx.scopedEquipmentInventory(model, "site-a", "rtu-1", { nowMs: now });
  const ids = inv.ioPoints.map((x) => x.uuid);
  assert.ok(ids.includes("p-temp"));
  assert.ok(ids.includes("p-sp"));
  assert.ok(ids.includes("p-cmd"));
  assert.ok(ids.includes("p-bool"));
  assert.ok(ids.includes("p-enum"));
  assert.ok(ids.includes("p-text"));
  assert.ok(ids.includes("p-dev-unambig"));
  assert.ok(!ids.includes("p-dev-ambig"), "ambiguous deviceRef point excluded");
  assert.ok(!ids.includes("p-wrong-site"), "wrong site point excluded");
  assert.ok(!ids.includes("p-fdd"), "FDD point excluded from physical I/O");

  assert.equal(inv.fddPoints.map((p) => p.uuid).join(","), "p-fdd");
  assert.equal(inv.gaps.length, 1);
  assert.equal(inv.gaps[0].point.uuid, "p-wrong-site");

  const tempRow = inv.ioPoints.find((x) => x.uuid === "p-temp");
  assert.equal(tempRow.rawValue, 0);
  assert.equal(tempRow.status, "trended");
  const boolRow = inv.ioPoints.find((x) => x.uuid === "p-bool");
  assert.equal(boolRow.rawValue, false);
  assert.equal(boolRow.formattedValue, "off");
  const cmdRow = inv.ioPoints.find((x) => x.uuid === "p-cmd");
  assert.equal(cmdRow.status, "current-only");
  const enumRow = inv.ioPoints.find((x) => x.uuid === "p-enum");
  assert.equal(enumRow.formattedValue, "2");
  const textRow = inv.ioPoints.find((x) => x.uuid === "p-text");
  assert.equal(textRow.formattedValue, "Normal");
});
