import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

const { toSI } = createRequire(import.meta.url)("../static/units.js");

test("unit aliases convert only the declared NF and BACnet spellings", () => {
  for (const unit of ["L/sec", "l/sec", "liters/second", "litres/second", "liters per second",
    "litres per second", "liters-per-second"]) {
    assert.deepEqual(toSI(1, unit), { value: 1, unit: "L/s", quantity: "flow" });
  }
  for (const unit of ["in h20", "inh20", "in h\u20820", "inches of water", "inches-of-water", "iwc", "in. w.c."]) {
    assert.deepEqual(toSI(1, unit), { value: 249.0889, unit: "Pa", quantity: "pressure" });
  }
  assert.equal(toSI(1, "cubic-feet-per-minute").value, 0.4719474);
  assert.equal(toSI(1, "pascals").value, 1);
  assert.equal(toSI(1, "kilopascals").value, 1000);
  assert.equal(toSI(68, "degrees-fahrenheit").value, 20);
  assert.equal(toSI(20, "degrees-celsius").value, 20);
  assert.equal(toSI(50, "percent").value, 50);
  assert.equal(toSI(50, "percent-relative-humidity").value, 50);
  for (const unit of ["h20", "unrecognized-unit", "constructor"]) assert.equal(toSI(1, unit), null);
});
