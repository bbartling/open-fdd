// node --test nf-app/tests/zone-band.test.mjs - the occupied zone temperature range (5.0.22): the SI band, its limits,
// clamping, defaults, the 2 F minimum deadband, SI storage / imperial display, and the calendar document that carries it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";

const require = createRequire(import.meta.url);
const Z = require("../hooks/lib/zone-band.js");
const O = require("../static/occupancy.js");
const F2C = (f) => (f - 32) * 5 / 9;
const C2F = (c) => c * 9 / 5 + 32;
const near = (a, b, e = 1e-9) => assert.ok(Math.abs(a - b) < e, `${a} != ${b}`);
const band = (lo, hi) => ({ lo_c: lo, hi_c: hi });
const nearBand = (got, lo, hi) => { near(got.lo_c, lo); near(got.hi_c, hi); };

test("the hook and the browser get the same file (generated copies of shared/zone-band.js)", () => {
  const body = (p) => readFileSync(new URL(p, import.meta.url), "utf8").split("\n").slice(1).join("\n");
  const src = readFileSync(new URL("../../shared/zone-band.js", import.meta.url), "utf8").replace(/\r\n/g, "\n");
  assert.equal(body("../hooks/lib/zone-band.js"), src);
  assert.equal(body("../static/zone-band.js"), src);
});

test("constants: limits 65-80 F, default 70-75 F (stored in degC), deadband 2 F = 10/9 K", () => {
  near(Z.LIMIT_LO_C, 18.333333333); near(Z.LIMIT_HI_C, 26.666666667);
  near(Z.DEFAULT_LO_C, 21.111111111); near(Z.DEFAULT_HI_C, 23.888888889);
  assert.equal(Z.MIN_DEADBAND_K, 10 / 9);
  near(Z.MIN_DEADBAND_K, 1.111111111);
  near(F2C(72) - F2C(70), Z.MIN_DEADBAND_K);                           // 2 F as a temperature difference
  assert.deepEqual(Z.defaultBand(), band(Z.DEFAULT_LO_C, Z.DEFAULT_HI_C));
});

test("defaults: a missing or unusable saved band resolves to 70-75 F, a good one is 'saved'", () => {
  for (const raw of [undefined, null, {}, { lo_c: 22 }, { lo_c: "x", hi_c: 24 }, { lo_c: 25, hi_c: 22 }, "21-24", [21, 24], { lo_c: NaN, hi_c: 24 }]) {
    const r = Z.resolveBand(raw);
    assert.equal(r.source, "default", JSON.stringify(raw));
    nearBand(r, Z.DEFAULT_LO_C, Z.DEFAULT_HI_C);
  }
  const ok = Z.resolveBand(band(20, 25));
  assert.equal(ok.source, "saved"); nearBand(ok, 20, 25);
  assert.ok(Z.resolveBand(null).reason && Z.resolveBand(band(25, 22)).reason.includes("inverted"));
});

test("clamping: never negative, always inside 65-80 F (18.333-26.667 C)", () => {
  nearBand(Z.validateBand(band(-5, 99)), Z.LIMIT_LO_C, Z.LIMIT_HI_C);              // negative low, huge high
  nearBand(Z.validateBand(band(-30, -10)), Z.LIMIT_LO_C, Z.LIMIT_LO_C + Z.MIN_DEADBAND_K);   // both negative: clamped, then the deadband
  nearBand(Z.validateBand(band(0, 15)), Z.LIMIT_LO_C, Z.LIMIT_LO_C + Z.MIN_DEADBAND_K);     // both below the floor
  nearBand(Z.validateBand(band(30, 40)), Z.LIMIT_HI_C - Z.MIN_DEADBAND_K, Z.LIMIT_HI_C);     // both above the ceiling
  nearBand(Z.validateBand(band(15, 22)), Z.LIMIT_LO_C, 22);
  nearBand(Z.validateBand(band(22, 31)), 22, Z.LIMIT_HI_C);
  nearBand(Z.validateBand({ lo_c: "20.5", hi_c: "24.5" }), 20.5, 24.5);                      // numeric strings (StartHook string maps)
  for (const b of [band(-1e9, 1e9), band(0, 100), band(21, 24)]) {
    const v = Z.validateBand(b);
    assert.ok(v.lo_c >= Z.LIMIT_LO_C - 1e-9 && v.hi_c <= Z.LIMIT_HI_C + 1e-9 && v.lo_c >= 0 && v.hi_c - v.lo_c >= Z.MIN_DEADBAND_K - 1e-9);
  }
});

test("rejected on a save: missing, NaN, non-numeric and inverted (lo > hi) bands", () => {
  assert.throws(() => Z.validateBand(undefined), /missing/);
  assert.throws(() => Z.validateBand(null), /missing/);
  assert.throws(() => Z.validateBand({}), /finite numbers/);
  assert.throws(() => Z.validateBand({ lo_c: 21 }), /finite numbers/);
  assert.throws(() => Z.validateBand({ lo_c: NaN, hi_c: 24 }), /finite numbers/);
  assert.throws(() => Z.validateBand({ lo_c: 21, hi_c: Infinity }), /finite numbers/);
  assert.throws(() => Z.validateBand({ lo_c: "warm", hi_c: 24 }), /finite numbers/);
  assert.throws(() => Z.validateBand({ lo_c: true, hi_c: 24 }), /finite numbers/);
  assert.throws(() => Z.validateBand({ lo_c: "", hi_c: 24 }), /finite numbers/);
  assert.throws(() => Z.validateBand("21-24"), /must be/);
  assert.throws(() => Z.validateBand([21, 24]), /must be/);
  assert.throws(() => Z.validateBand(band(25, 22)), /inverted/);
  assert.throws(() => Z.validateBand(band(Z.LIMIT_HI_C, Z.LIMIT_LO_C)), /inverted/);
});

test("minimum deadband 2 F: exactly at it is kept, just under it is widened, equal handles are widened", () => {
  const exactly = Z.validateBand(band(21, 21 + Z.MIN_DEADBAND_K));
  nearBand(exactly, 21, 21 + Z.MIN_DEADBAND_K);                                   // exactly 2 F apart: unchanged
  const exactF = Z.validateBand(band(F2C(70), F2C(72)));
  nearBand(exactF, F2C(70), F2C(72));                                              // 70 F .. 72 F is accepted as is
  const under = Z.validateBand(band(21, 21 + Z.MIN_DEADBAND_K - 0.001));
  nearBand(under, 21, 21 + Z.MIN_DEADBAND_K);                                      // just under: the high handle is pushed out
  nearBand(Z.validateBand(band(22, 22)), 22, 22 + Z.MIN_DEADBAND_K);               // equal handles
  nearBand(Z.validateBand(band(21, 21.5)), 21, 21 + Z.MIN_DEADBAND_K);
  for (const b of [exactly, exactF, under]) assert.ok(b.hi_c - b.lo_c >= Z.MIN_DEADBAND_K - 1e-9);
});

test("range limits: lo 79 F / hi 80 F, lo 65 F / hi 66 F, both on a limit", () => {
  const top = Z.validateBand(band(F2C(79), F2C(80)));
  nearBand(top, F2C(78), F2C(80));                                                 // 1 F gap at the ceiling: the low handle gives way
  const bottom = Z.validateBand(band(F2C(65), F2C(66)));
  nearBand(bottom, F2C(65), F2C(67));
  nearBand(Z.validateBand(band(F2C(80), F2C(80))), F2C(78), F2C(80));
  nearBand(Z.validateBand(band(F2C(65), F2C(65))), F2C(65), F2C(67));
  nearBand(Z.validateBand(band(F2C(65), F2C(80))), F2C(65), F2C(80));              // the full range is valid
  nearBand(Z.validateBand(band(F2C(78), F2C(80))), F2C(78), F2C(80));              // exactly 2 F at the ceiling
  nearBand(Z.validateBand(band(F2C(65), F2C(67))), F2C(65), F2C(67));              // exactly 2 F at the floor
});

test("slider handles: low never above high - 2 F, high never below low + 2 F, both stay inside the limits", () => {
  const b = band(21.111111111, 23.888888889);
  nearBand(Z.moveHandle(b, "lo", 30), 23.888888889 - Z.MIN_DEADBAND_K, 23.888888889);   // dragged past the high handle: stops 2 F short
  nearBand(Z.moveHandle(b, "lo", 23.5), 23.888888889 - Z.MIN_DEADBAND_K, 23.888888889);
  nearBand(Z.moveHandle(b, "lo", 22), 22, 23.888888889);
  nearBand(Z.moveHandle(b, "lo", -10), Z.LIMIT_LO_C, 23.888888889);                     // negative -> the floor
  nearBand(Z.moveHandle(b, "hi", 10), 21.111111111, 21.111111111 + Z.MIN_DEADBAND_K);   // dragged below the low handle: stops 2 F above it
  nearBand(Z.moveHandle(b, "hi", 21.5), 21.111111111, 21.111111111 + Z.MIN_DEADBAND_K);
  nearBand(Z.moveHandle(b, "hi", 25), 21.111111111, 25);
  nearBand(Z.moveHandle(b, "hi", 99), 21.111111111, Z.LIMIT_HI_C);
  assert.deepEqual(Z.moveHandle(b, "lo", NaN), b);                                       // NaN / junk moves nothing
  assert.deepEqual(Z.moveHandle(b, "hi", "junk"), b);
  assert.throws(() => Z.moveHandle(b, "mid", 22), /lo.*hi/);
  // a drag sequence can never produce an invalid band
  let cur = b;
  for (const [w, v] of [["lo", 25], ["hi", 18], ["lo", 26.5], ["hi", 26.7], ["lo", 18], ["hi", 18.5], ["lo", 100], ["hi", -3]]) {
    cur = Z.moveHandle(cur, w, v);
    assert.ok(cur.lo_c >= Z.LIMIT_LO_C - 1e-9 && cur.hi_c <= Z.LIMIT_HI_C + 1e-9 && cur.hi_c - cur.lo_c >= Z.MIN_DEADBAND_K - 1e-9, JSON.stringify(cur));
  }
});

test("SI is stored and shown by default; imperial is display only", () => {
  assert.equal(Z.unitLabel(), "°C"); assert.equal(Z.unitLabel("si"), "°C"); assert.equal(Z.unitLabel("imperial"), "°F");
  assert.equal(Z.toDisplay(22, undefined), 22); assert.equal(Z.toDisplay(22, "si"), 22);
  near(Z.toDisplay(Z.DEFAULT_LO_C, "imperial"), 70); near(Z.toDisplay(Z.DEFAULT_HI_C, "imperial"), 75);
  near(Z.fromDisplay(72, "imperial"), F2C(72)); assert.equal(Z.fromDisplay(22.5, "si"), 22.5);
  for (const c of [18.333333333333332, 21.1, 23.9, 26.666666666666668]) near(Z.fromDisplay(Z.toDisplay(c, "imperial"), "imperial"), c);
  assert.equal(Z.describe(Z.defaultBand(), "si"), "21.1–23.9 °C");
  assert.equal(Z.describe(Z.defaultBand(), "imperial"), "70–75 °F");
  const si = Z.sliderSpec("si"), ip = Z.sliderSpec("imperial");
  assert.deepEqual([si.unit, si.min, si.max, si.step], ["°C", 18.3, 26.7, 0.1]);
  assert.deepEqual([ip.unit, ip.min, ip.max, ip.step, ip.minGap], ["°F", 65, 80, 1, 2]);
  assert.equal(si.gapLabel, "1.11 K"); assert.equal(ip.gapLabel, "2 °F");
  // moving a handle in imperial stores degC
  const moved = Z.moveHandle(Z.defaultBand(), "hi", Z.fromDisplay(77, "imperial"));
  near(moved.hi_c, F2C(77)); assert.ok(moved.hi_c < 30 && C2F(moved.hi_c) > 76.99);
});

test("rule parameters: the band fills the comfort pairs, an explicit per-rule tuning always wins", () => {
  const controls = { zone_t_lo: {}, zone_t_hi: {}, confirm_min: {} };
  const eff = { zone_t_lo: Z.DEFAULT_LO_C, zone_t_hi: Z.DEFAULT_HI_C, confirm_min: 15 };
  const b = band(20, 25);
  const none = Z.applyToEffective(controls, eff, new Set(), b);
  assert.deepEqual([none.effective.zone_t_lo, none.effective.zone_t_hi, none.effective.confirm_min], [20, 25, 15]);
  assert.deepEqual(none.applied, { zone_t_lo: 20, zone_t_hi: 25 });
  const both = Z.applyToEffective(controls, { ...eff, zone_t_lo: 19, zone_t_hi: 27 }, new Set(["zone_t_lo", "zone_t_hi"]), b);
  assert.deepEqual([both.effective.zone_t_lo, both.effective.zone_t_hi], [19, 27]); assert.deepEqual(both.applied, {}); assert.equal(both.skipped.length, 1);
  const onlyHi = Z.applyToEffective(controls, { ...eff, zone_t_hi: 26 }, new Set(["zone_t_hi"]), b);
  assert.deepEqual([onlyHi.effective.zone_t_lo, onlyHi.effective.zone_t_hi], [20, 26]);
  const onlyLo = Z.applyToEffective(controls, { ...eff, zone_t_lo: 22 }, new Set(["zone_t_lo"]), b);
  assert.deepEqual([onlyLo.effective.zone_t_lo, onlyLo.effective.zone_t_hi], [22, 25]);
  // an explicit key that would leave the band less than 2 F wide is not mixed with the band's other edge
  const tight = Z.applyToEffective(controls, { ...eff, zone_t_lo: 24.5 }, new Set(["zone_t_lo"]), b);
  assert.equal(tight.effective.zone_t_hi, Z.DEFAULT_HI_C); assert.deepEqual(tight.applied, {});
  const sched = Z.applyToEffective({ comfort_low: {}, comfort_high: {} }, { comfort_low: 21, comfort_high: 24 }, new Set(), b);
  assert.deepEqual([sched.effective.comfort_low, sched.effective.comfort_high], [20, 25]);
  const unrelated = Z.applyToEffective({ confirm_min: {} }, { confirm_min: 5 }, new Set(), b);
  assert.deepEqual(unrelated.effective, { confirm_min: 5 }); assert.deepEqual(unrelated.pairs, []);
  assert.deepEqual(Z.applyToEffective(controls, eff, new Set(), null).effective, eff);        // no band: untouched
});

test("the calendar document carries the band: round trip, lenient read, strict save, persists per site", () => {
  const cal = O.normalizeCalendar({ timezone: "America/Chicago", zone_band: { lo_c: 20, hi_c: 25 } });
  assert.deepEqual(cal.zone_band, { lo_c: 20, hi_c: 25 });
  assert.deepEqual(O.normalizeCalendarOverride({ version: 1, calendar: cal }), { version: 1, calendar: cal }, "round trip");
  assert.equal("zone_band" in O.normalizeCalendar({ timezone: "America/Chicago" }), false, "an old calendar has no band: the default applies");
  assert.deepEqual(O.zoneBandOf(cal), { lo_c: 20, hi_c: 25, source: "saved" });
  const def = O.zoneBandOf(O.defaultCalendar());
  assert.equal(def.source, "default"); near(def.lo_c, Z.DEFAULT_LO_C); near(def.hi_c, Z.DEFAULT_HI_C);
  // reading a stored value with a bad band drops it (the default applies); saving one is refused
  for (const bad of [{ lo_c: 25, hi_c: 22 }, { lo_c: "x", hi_c: 22 }, {}, { lo_c: NaN, hi_c: 22 }]) {
    assert.equal("zone_band" in O.normalizeCalendar({ zone_band: bad }), false, JSON.stringify(bad));
    assert.throws(() => O.normalizeCalendarOverride({ version: 1, calendar: { zone_band: bad } }), /zone_band/, JSON.stringify(bad));
  }
  // a save clamps an out-of-range band and widens a narrow one (the saved document is already canonical)
  const saved = O.normalizeCalendarOverride({ version: 1, calendar: { zone_band: { lo_c: -4, hi_c: 40 } } }).calendar.zone_band;
  nearBand(saved, Z.LIMIT_LO_C, Z.LIMIT_HI_C);
  const narrow = O.normalizeCalendarOverride({ version: 1, calendar: { zone_band: { lo_c: 22, hi_c: 22.2 } } }).calendar.zone_band;
  nearBand(narrow, 22, 22 + Z.MIN_DEADBAND_K);
  // the weekly schedule built from the calendar still works with the band present
  assert.equal(O.calendarSchedule(cal).hoursPerWeek, 60);
});