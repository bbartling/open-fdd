// node --test nf-app/tests/zone-band-editor.test.mjs - the Overview slider (static/occupancy-editor.js) on a tiny fake DOM:
// the dual handles, the 2 F minimum gap enforced while dragging, SI by default / imperial display only, SI storage,
// Save carrying zone_band in the calendar document, and no inline styles (CSP).
import { test } from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import { readFileSync } from "node:fs";

const dir = new URL("../static/", import.meta.url);
const F2C = (f) => (f - 32) * 5 / 9;
const near = (a, b, e = 1e-6) => assert.ok(Math.abs(a - b) < e, `${a} != ${b}`);

class El {
  constructor(tag) { this.tagName = tag; this.children = []; this.attrs = {}; this.listeners = {}; this.textContent = ""; this.value = ""; this.checked = false; this.disabled = false; this.hidden = false; this.isConnected = true; this.id = ""; }
  append(...n) { this.children.push(...n); }
  replaceChildren(...n) { this.children = []; this.append(...n); }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  fire(t) { for (const f of this.listeners[t] || []) f({ target: this }); }
  find(id) { if (this.id === id) return this; for (const c of this.children) { const r = c.find && c.find(id); if (r) return r; } return null; }
  walk(fn) { fn(this); for (const c of this.children) if (c.walk) c.walk(fn); }
}

function setup({ units = "si", saved = null } = {}) {
  const host = new El("section"); host.id = "overviewOccupancy";
  const saves = [];
  const ctx = vm.createContext({
    console, Intl, Date, Math, JSON,
    localStorage: { getItem: () => units },
    document: { getElementById: (id) => (id === "overviewOccupancy" ? host : null), createElement: (t) => new El(t), createElementNS: (_ns, t) => new El(t) },
  });
  ctx.globalThis = ctx;
  ctx.ofddTuning = { async callHook(a) {
    if (a.action === "get") return saved ? { ok: true, source: "saved", calendar: saved, active: { site: { revision: 4 } } } : { ok: true, source: "default", active: {} };
    saves.push(a);
    return { ok: true, calendar: a.overrides.calendar, revision: 5 };
  } };
  for (const f of ["units.js", "zone-band.js", "occupancy.js", "occupancy-editor.js"]) vm.runInContext(readFileSync(new URL(f, dir), "utf8"), ctx, { filename: f });
  return { host, ctx, saves, ZB: ctx.ofddZoneBand };
}
const mount = async (s, redraws = []) => { await s.ctx.ofddOccupancyEditor.render({ site: "S1", timezone: "America/Chicago", onChange: () => { redraws.push(1); } }); return s.host.find("zoneBand"); };
const drag = (el, v, commit = true) => { el.value = String(v); el.fire("input"); if (commit) el.fire("change"); };

test("SI by default: two handles at 21.1 and 23.9 C, limits 18.3 - 26.7 C, 1.11 K minimum gap shown", async () => {
  const s = setup(); const panel = await mount(s);
  assert.ok(panel, "the slider panel is on the Overview next to the calendar");
  const lo = s.host.find("zbLo"), hi = s.host.find("zbHi");
  assert.deepEqual([lo.type, hi.type], ["range", "range"]);
  assert.deepEqual([lo.min, lo.max, lo.step], ["18.3", "26.7", "0.1"]);
  assert.deepEqual([lo.value, hi.value], ["21.1", "23.9"]);
  assert.match(s.host.find("zbReadout").textContent, /Low 21\.1 °C · High 23\.9 °C · default/);
  assert.ok(JSON.stringify(panel, (k, v) => (k === "listeners" ? undefined : v)).includes("1.11 K"), "the deadband is shown with its unit");
  assert.ok(s.host.find("zbLo").attrs["aria-label"].includes("°C"));
});

test("imperial is display only: the same band reads 70 - 75 F with 65 - 80 F limits and a 2 F gap", async () => {
  const s = setup({ units: "imperial" }); const panel = await mount(s);
  const lo = s.host.find("zbLo"), hi = s.host.find("zbHi");
  assert.deepEqual([lo.min, lo.max, lo.step, lo.value, hi.value], ["65", "80", "1", "70", "75"]);
  assert.match(s.host.find("zbReadout").textContent, /Low 70 °F · High 75 °F · default/);
  assert.ok(JSON.stringify(panel, (k, v) => (k === "listeners" ? undefined : v)).includes("2 °F"));
  drag(hi, 78);                                                                       // a degF drag stores degC
  assert.equal(s.ctx.ofddOccCalendars.S1.zone_band.lo_c.toFixed(4), F2C(70).toFixed(4));
  near(s.ctx.ofddOccCalendars.S1.zone_band.hi_c, F2C(78));
});

test("dragging: the low handle stops 2 F below the high one, the high handle stops 2 F above the low one", async () => {
  const s = setup({ units: "imperial" }); await mount(s);
  const lo = s.host.find("zbLo"), hi = s.host.find("zbHi");
  drag(lo, 79);                                                                       // way past the high handle (75 F)
  assert.equal(lo.value, "73"); assert.equal(hi.value, "75");
  drag(hi, 60);                                                                       // below the low handle
  assert.equal(hi.value, "75"); assert.equal(lo.value, "73");
  drag(lo, 60);                                                                       // below the floor
  assert.equal(lo.value, "65");
  drag(hi, 66);                                                                       // 1 F above the low handle
  assert.equal(hi.value, "67");
  drag(hi, 99);                                                                       // above the ceiling
  assert.equal(hi.value, "80");
  drag(lo, 79);                                                                       // lo 79 / hi 80: 1 F gap is refused
  assert.equal(lo.value, "78"); assert.equal(hi.value, "80");
  const b = s.ctx.ofddOccCalendars.S1.zone_band;
  assert.ok(b.lo_c >= s.ZB.LIMIT_LO_C - 1e-9 && b.hi_c <= s.ZB.LIMIT_HI_C + 1e-9 && b.hi_c - b.lo_c >= s.ZB.MIN_DEADBAND_K - 1e-9);
});

test("dragging in SI keeps the same rules in degC and never goes negative", async () => {
  const s = setup(); await mount(s);
  const lo = s.host.find("zbLo"), hi = s.host.find("zbHi");
  drag(lo, -5); assert.equal(lo.value, "18.3");
  drag(hi, 18.5); assert.equal(hi.value, (18.3333333333 + 10 / 9).toFixed(1));          // 19.4: the high handle stops 1.11 K above
  drag(hi, 40); assert.equal(hi.value, "26.7");
  assert.ok(s.ctx.ofddOccCalendars.S1.zone_band.lo_c > 0);
});

test("charts redraw when a handle is released, Save stores the band (degC) in the calendar document, per site", async () => {
  const s = setup(); const redraws = [];
  await mount(s, redraws);
  const hi = s.host.find("zbHi");
  drag(hi, 25.5, false); assert.equal(redraws.length, 0, "no chart redraw while dragging");
  hi.fire("change"); assert.equal(redraws.length, 1, "redraw on release");
  assert.equal(s.host.find("zbSave").disabled, false);
  s.host.find("zbSave").fire("click");
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(s.saves.length, 1);
  const a = s.saves[0];
  assert.deepEqual([a.action, a.site, a.scope, a.rule_id], ["save", "S1", "site", "OCC-CALENDAR"]);
  assert.equal(a.overrides.version, 1);
  near(a.overrides.calendar.zone_band.lo_c, s.ZB.DEFAULT_LO_C); near(a.overrides.calendar.zone_band.hi_c, 25.5);
  assert.match(s.host.find("zbStatus").textContent, /Saved \(revision 5\)/);
});

test("a saved band loads, the default button restores 70-75 F, and a bad saved band falls back to the default", async () => {
  const s = setup({ saved: { timezone: "America/Chicago", zone_band: { lo_c: 20, hi_c: 25 }, days: {} } });
  await mount(s);
  assert.deepEqual([s.host.find("zbLo").value, s.host.find("zbHi").value], ["20", "25"]);
  assert.match(s.host.find("zbReadout").textContent, /custom/);
  s.host.find("zbDefault").fire("click");
  assert.deepEqual([s.host.find("zbLo").value, s.host.find("zbHi").value], ["21.1", "23.9"]);
  const bad = setup({ saved: { timezone: "America/Chicago", zone_band: { lo_c: 26, hi_c: 20 }, days: {} } });
  await mount(bad);
  assert.deepEqual([bad.host.find("zbLo").value, bad.host.find("zbHi").value], ["21.1", "23.9"]);
  assert.match(bad.host.find("zbReadout").textContent, /default/);
});

test("CSP-safe: plain JS, no inline style attributes or style-property writes anywhere in the editor or slider", async () => {
  const src = readFileSync(new URL("occupancy-editor.js", dir), "utf8") + readFileSync(new URL("zone-band.js", dir), "utf8");
  assert.doesNotMatch(src, /\.style\b|setAttribute\(\s*["']style|cssText|innerHTML|<style/);
  const s = setup(); await mount(s);
  s.host.walk((n) => { assert.equal("style" in n.attrs, false); assert.equal(n.style, undefined); });
});