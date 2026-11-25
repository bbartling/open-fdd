// node --test nf-app/tests/equip-kinds.test.mjs — #1777: Haystack 4 plant conjuncts (hot-water-plant, …) get the same
// equipment kind and rules as the camelCase / boiler marker forms. fdd.js is the binding code both the FDD tab and the
// FDD hook run (hooks/fdd.js loads it unchanged), so one check covers UI and hook.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const dir = new URL("../static/", import.meta.url);
const catalog = JSON.parse(readFileSync(new URL("fdd-catalog.json", dir), "utf8"));
const load = (...files) => {
  const ctx = vm.createContext({ console, URLSearchParams, TextDecoder, atob, btoa });
  for (const f of files) vm.runInContext(readFileSync(new URL(f, dir), "utf8"), ctx, { filename: f });
  ctx.get = (name) => vm.runInContext(name, ctx);
  return ctx;
};

const equip = (id, markers) => ({ uuid: `u-${id}`, name: id, pointType: "EQUIPMENT", attrs: { id, siteRef: "s", markers } });
const point = (id, equipRef, markers) => ({ uuid: `u-${id}`, name: id, pointType: "POINT",
  attrs: { siteRef: "s", equipRef, markers, kind: "Number", unit: "°C" } });

const PLANTS = {
  boiler: ["equip,boiler", "equip,hotWaterPlant", "equip,hot,water,heat,plant,hot-water-plant", "equip,hot,water,plant",
    "equip,hot-water-plant", "equip,steamPlant", "equip,steam,plant,steam-plant"],
  chwPlant: ["equip,chilledWaterPlant", "equip,chilled,water,plant,chilled-water-plant", "equip,chilled,water,plant"],
  cooling_tower: ["equip,coolingTower", "equip,condenser,water,plant,condenser-water-plant"],
};

test("Haystack 4 plant conjuncts map to the same kind as the camelCase / boiler markers", () => {
  const ctx = load("paging.js", "nf.js", "model.js", "fdd.js");
  for (const [kind, forms] of Object.entries(PLANTS)) {
    for (const markers of forms) {
      assert.deepEqual(Array.from(ctx.equipKinds(equip("P", markers), catalog)).filter((k) => k !== "general"), [kind], markers);
    }
  }
  // a conjunct needs every part: a hot-water pump or a bare plant is not a boiler
  for (const markers of ["equip,hot,water,pump", "equip,plant", "equip,water,plant"]) {
    assert.deepEqual(Array.from(ctx.equipKinds(equip("P", markers), catalog)), ["general"], markers);
  }
  // a combined plant (hot, chilled, water, plant) has both kinds, like an equip tagged boiler and chiller: both rule
  // families apply, and each binds only the roles whose points the plant has
  for (const markers of ["equip,hot,chilled,water,plant", "equip,boiler,chiller"]) {
    const kinds = Array.from(ctx.equipKinds(equip("P", markers), catalog));
    assert.ok(kinds.includes("boiler") && (kinds.includes("chwPlant") || kinds.includes("chiller")), markers);
  }
  assert.deepEqual(Array.from(ctx.equipKinds(equip("P", "equip,hot,chilled,water,plant"), catalog)), ["chwPlant", "boiler", "general"]);
});

test("a Haystack 4 hot-water plant binds the boiler rules exactly like a boiler-marker plant", () => {
  const ctx = load("paging.js", "nf.js", "model.js", "fdd.js");
  const rulesOf = (markers) => {
    const e = equip("HWP", markers);
    const model = { sites: [], equips: [e], devices: [],
      points: [point("HWS", "HWP", "point,sensor,hot,water,leaving,temp,his")].map(ctx.toPoint) };
    return Array.from(ctx.equipRules(e, model, catalog), (r) => [r.rule.id, r.runnable, Object.keys(r.bound).filter((k) => r.bound[k].length)]);
  };
  const boiler = rulesOf("equip,boiler");
  const ids = boiler.map(([id]) => id);
  for (const id of ["SV-RANGE", "PID-HUNT-1", "TRIM-3", "SCHED-247"]) assert.ok(ids.includes(id), id);
  assert.ok(boiler.find(([id]) => id === "SV-RANGE")[2].includes("hw_supply_t"));
  assert.deepEqual(rulesOf("equip,hot,water,heat,plant,hot-water-plant"), boiler);
  assert.deepEqual(rulesOf("equip,hot,water,plant"), boiler);
  assert.deepEqual(rulesOf("equip,hotWaterPlant"), boiler);
});

test("the Overview auto-pick and the FDD binding agree: a Haystack 4 hot-water plant is a boiler", () => {
  const ctx = load("units.js", "paging.js", "nf.js", "model.js", "fdd.js", "charts.js");
  const e = equip("HWP", "equip,hot,water,heat,plant,hot-water-plant");
  assert.equal(ctx.get("overviewEquipClass")(e), "boiler");
  assert.ok(Array.from(ctx.equipKinds(e, catalog)).includes("boiler"));
});

test("RDF export writes plant and the Haystack 4 plant conjuncts under phIoT, not local", () => {
  const ctx = load("paging.js", "nf.js", "model.js");
  const e = equip("HWP", "equip,hot,water,heat,plant,hot-water-plant");
  const { turtle, nonStandard } = ctx.modelToTurtle({ sites: [], equips: [e], devices: [], points: [] }, "urn:test:");
  assert.deepEqual([...nonStandard], []);
  assert.match(turtle, /phIoT:plant\b/);
  assert.match(turtle, /phIoT:hot-water-plant\b/);
  assert.doesNotMatch(turtle, /local:(plant|hot-water-plant)\b/);
});
