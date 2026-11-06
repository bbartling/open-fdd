// node --test nf-app/tests/rdf.test.mjs — slice 6: external time-series refs in the Turtle export.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const dir = new URL("../static/", import.meta.url);
const load = () => {
  const ctx = vm.createContext({ console, URLSearchParams, TextDecoder, atob, btoa });
  for (const f of ["nf.js", "model.js"]) vm.runInContext(readFileSync(new URL(f, dir), "utf8"), ctx, { filename: f });
  ctx.get = (name) => vm.runInContext(name, ctx);
  return ctx;
};
const rec = (name, attrs) => ({ uuid: `uuid-${name}`, name, pointType: "POINT", attrs });
const model = (ctx) => ({
  sites: [{ uuid: "s", name: "S", pointType: "SITE", attrs: { id: "s" } }],
  equips: [{ uuid: "e", name: "E", pointType: "EQUIPMENT", attrs: { id: "E", siteRef: "s", markers: "equip" } }],
  devices: [],
  points: [
    rec("A", { siteRef: "s", equipRef: "E", markers: "point,sensor,temp,his" }),
    rec("B", { siteRef: "s", equipRef: "E", markers: "point,cmd,fan,his" }),
    rec("X", { siteRef: "s" }),   // untagged: not exported
  ].map(ctx.toPoint),
});

test("every exported point has exactly one NF time-series reference with its uuid", () => {
  const ctx = load();
  const { turtle } = ctx.modelToTurtle(model(ctx), "urn:test:", { nfBase: "http://nf.example.test/" });
  assert.equal((turtle.match(/ref:hasExternalReference/g) || []).length, 2);
  for (const u of ["uuid-A", "uuid-B"]) {
    assert.ok(turtle.includes(`ref:hasTimeseriesId "${u}"`), u);
    assert.ok(turtle.includes(`<http://nf.example.test/api/v1/point/data?uuids=${u}>`), `url for ${u}`);
  }
  assert.ok(!turtle.includes("uuid-X"));
  assert.match(turtle, /@prefix ref: <https:\/\/brickschema\.org\/schema\/Brick\/ref#> \./);
});

test("the store node is defined and no TimescaleDB store appears without the option", () => {
  const ctx = load();
  const { turtle } = ctx.modelToTurtle(model(ctx), "urn:test:", { nfBase: "http://nf.example.test" });
  assert.match(turtle, /^local:store_nf\n\s+a ref:Database/m);
  assert.ok(!turtle.includes("store_timescaledb"));
  assert.ok(!turtle.includes("http://nf.example.test//"), "no double slash from the base");
});

test("full-profile hook adds a second reference per point and defines the store", () => {
  const ctx = load();
  const { turtle } = ctx.modelToTurtle(model(ctx), "urn:test:", { nfBase: "http://nf", timescale: { label: "TSDB" } });
  assert.equal((turtle.match(/ref:storedAt local:store_timescaledb/g) || []).length, 2);
  assert.match(turtle, /^local:store_timescaledb\n\s+a ref:Database/m);
});

test("no page origin and no nfBase: uuid-only reference, no URL, nothing hard-coded", () => {
  const ctx = load();
  const { turtle } = ctx.modelToTurtle(model(ctx), "urn:test:");
  assert.ok(turtle.includes('ref:hasTimeseriesId "uuid-A"'));
  assert.ok(!/schema:url <http/.test(turtle));
  assert.ok(!/\d+\.\d+\.\d+\.\d+/.test(turtle));
});
