// Sweep role-limit overrides (#1589): the JS twin (hooks/lib/role-limits.js) renders exactly what the Python renderer
// renders, converts display units to SI, enforces precedence and validation; the tuning editor helpers (static/tuning.js)
// and the fdd hook's per-equipment loader use it.
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";

const require = createRequire(import.meta.url);
const RL = require("../hooks/lib/role-limits.js");
const tuning = require("../static/tuning.js");
const hook = require("../hooks/fdd.js");
const tuningHook = require("../hooks/tuning.js");
const pack = JSON.parse(readFileSync(new URL("../rules/pack-postgres.json", import.meta.url), "utf8"));
const fixture = JSON.parse(readFileSync(new URL("./fixtures/role-limit-overrides.json", import.meta.url), "utf8"));
const T = pack.role_limit_templates;
const sha = (t) => createHash("sha256").update(t).digest("hex");

test("the hook and the browser get the same file (generated copies of shared/role-limits.js)", () => {
  const body = (p) => readFileSync(new URL(p, import.meta.url), "utf8").split("\n").slice(1).join("\n");
  assert.equal(body("../hooks/lib/role-limits.js"), body("../static/role-limits.js"));
});

test("templates filled with the shipped limits are byte-identical to the pack SQL and timelines", () => {
  const limits = RL.effectiveRoleLimits(T.shipped, T.allowlists);
  const out = RL.renderSweeps(pack, limits);
  assert.deepEqual(Object.keys(out).sort(), [...RL.SWEEP_RULES].sort());
  for (const id of RL.SWEEP_RULES) {
    assert.equal(out[id].sql, pack.rules[id].sql, id);
    assert.equal(out[id].timeline_sql, pack.rules[id].timeline_sql, `${id} timeline`);
  }
});

test("with overrides the JS render == Python render_rule(role_limits=...) and the config hash matches", () => {
  for (const c of fixture.cases) {
    const limits = RL.effectiveRoleLimits(T.shipped, T.allowlists, c.site, c.equipment);
    const out = RL.renderSweeps(pack, limits);
    for (const id of RL.SWEEP_RULES) assert.equal(sha(out[id].sql), c.sql_sha256[id], `${c.name}: ${id}`);
    const text = RL.configText(c.site, c.equipment);
    assert.equal(text ? sha(text) : "", c.config_hash, c.name);
  }
});

test("Python number text: repr and six-decimal half-up", () => {
  assert.equal(RL.pyRepr(20), "20.0");
  assert.equal(RL.pyRepr(1e-5), "1e-05");
  assert.equal(RL.pyRepr(1e16), "1e+16");
  assert.equal(RL.pyRepr(-51.111111), "-51.111111");
  assert.equal(RL.num(54.4444445), "54.444445");
  assert.equal(RL.num(1.6666665), "1.666667");
  assert.equal(RL.num(-0.0000005), "-1e-06");
  assert.equal(RL.num(870.94), "870.94");
});

test("display units -> SI: absolute temperature, difference and rate are separate conversions", () => {
  const q = "absolute_temperature";
  assert.ok(Math.abs(RL.toSi(32, "degF", q, "lo")) < 1e-12);
  assert.ok(Math.abs(RL.toSi(9, "degF", q, "spike_delta") - 5) < 1e-12);
  assert.ok(Math.abs(RL.toSi(1.8, "degF", q, "rate_per_h") - 1) < 1e-12);
  assert.equal(RL.toSi(1, "inH2O", "air_pressure", "hi"), 249.0889);
  assert.equal(RL.toSi(1, "cfm", "volume_flow", "hi"), 0.4719474);
  assert.equal(RL.toSi(1, "gpm", "volume_flow", "hi"), 0.0630902);
  for (const [qq, unit] of [["absolute_temperature", "degF"], ["air_pressure", "inH2O"], ["volume_flow", "cfm"], ["volume_flow", "gpm"]]) {
    for (const f of Object.keys(RL.FIELD_KIND)) for (const v of [-40, 0, 55.5, 1234.5]) {
      assert.ok(Math.abs(RL.fromSi(RL.toSi(v, unit, qq, f), unit, qq, f) - v) < 1e-9, `${qq} ${unit} ${f} ${v}`);
    }
  }
  assert.throws(() => RL.toSi(1, "inH2O", "absolute_temperature", "lo"), /not a temperature unit/);
  assert.throws(() => RL.toSi(NaN, "degC", "absolute_temperature", "lo"), /finite/);
});

test("invalid overrides are rejected; precedence is shipped < site < equipment", () => {
  const eff = (s, e) => RL.effectiveRoleLimits(T.shipped, T.allowlists, s, e);
  assert.throws(() => eff({ version: 1, roles: { "zone-air-temp": { lo: 30, hi: 20 } } }), /lo \(30\) must be < hi \(20\)/);
  assert.throws(() => eff({ version: 1, roles: { "zone-air-temp": { spike_delta: 0 } } }), /> 0/);
  assert.throws(() => eff({ version: 1, roles: { "no-role": { lo: 1 } } }), /unknown role/);
  assert.throws(() => eff({ version: 1, roles: { "zone-air-temp": { source: 1 } } }), /not editable/);
  assert.throws(() => eff({ version: 2, roles: {} }), /version/);
  const { doc, sources } = RL.merge(T.shipped, { version: 1, roles: { "zone-air-temp": { lo: 12, hi: 30 } } }, { version: 1, roles: { "zone-air-temp": { hi: 27 } } }, { site: 4, equipment: 2 });
  const zat = doc.roles.find((e) => e.role === "zone-air-temp");
  assert.deepEqual([zat.lo, zat.hi, zat.source], [12, 27, "equipment override revision 2"]);
  assert.deepEqual([sources["zone-air-temp"].lo, sources["zone-air-temp"].hi, sources["zone-air-temp"].spike_delta], ["site", "equipment", "shipped"]);
});

test("editor: imperial edits become SI overrides; unchanged cells keep their exact SI value; '' clears a field", () => {
  const limits = RL.merge(T.shipped).doc;
  const effective = { roles: Object.fromEntries(limits.roles.map((e) => [e.role, e])), sources: RL.merge(T.shipped).sources };
  const rows = tuning.displayRows(effective, "imperial");
  const zat = rows.find((r) => r.role === "zone-air-temp");
  assert.equal(zat.unit, "degF");
  assert.equal(rows.find((r) => r.role === "chw-flow").unit, "gpm");
  assert.equal(rows.find((r) => r.role === "duct-static-pressure").unit, "inH2O");
  const ov = tuning.buildOverride({ "zone-air-temp": { lo: "55", hi: String(zat.fields.hi.shown), spike_delta: "9" }, "duct-static-pressure": { hi: "2" } }, rows, null);
  assert.deepEqual(ov, { version: 1, roles: { "zone-air-temp": { lo: 12.777778, spike_delta: 5 }, "duct-static-pressure": { hi: 498.1778 } } });
  const cleared = tuning.buildOverride({ "zone-air-temp": { lo: "" } }, rows, ov);
  assert.deepEqual(cleared.roles["zone-air-temp"], { spike_delta: 5 });
  assert.throws(() => tuning.buildOverride({ "zone-air-temp": { lo: "warm" } }, rows, null), /not a number/);
  const si = tuning.displayRows(effective, "si");
  assert.equal(si.find((r) => r.role === "zone-air-temp").unit, "degC");
  const opt = tuning.bandChartOption(rows, T.shipped, "absolute_temperature");
  assert.equal(opt.yAxis.data.length, rows.filter((r) => r.quantity === "absolute_temperature").length);
  assert.equal(opt.series.length, 4);
});

test("fdd hook: no overrides -> shipped pack SQL; site + equipment revisions -> per-equipment SQL and provenance", async () => {
  const none = await hook.loadRoleLimitOverrides({ engine: { roleLimitOverrides: async () => [] }, pack, log: () => {} });
  assert.equal(none.forEquip("s", "e"), null);
  const noTs = await hook.loadRoleLimitOverrides({ engine: {}, pack, log: () => {} });
  assert.equal(noTs.summary.source, "shipped");
  const rows = [
    { site_id: "s", scope_key: "site", revision: 3, parameters: { version: 1, roles: { "zone-air-temp": { lo: 12, hi: 30 } } } },
    { site_id: "s", scope_key: "equip:VAV-1", revision: 5, parameters: { version: 1, roles: { "zone-air-temp": { hi: 27 } } } },
    { site_id: "s", scope_key: "equip:VAV-BAD", revision: 1, parameters: { version: 1, roles: { "zone-air-temp": { lo: 40 } } } },
    { site_id: "s", scope_key: "equip:VAV-RESET", revision: 2, parameters: { version: 1, roles: {}, reset: true } },
  ];
  const logs = [];
  const t = await hook.loadRoleLimitOverrides({ engine: { roleLimitOverrides: async () => rows }, pack, log: (m) => logs.push(m) });
  const v1 = t.forEquip("s", "VAV-1");
  assert.equal(v1.configRevision, 5);
  assert.deepEqual(v1.parameters.role_limits.overrides, { site: { "zone-air-temp": { hi: 30.0, lo: 12.0 } }, equipment: { "zone-air-temp": { hi: 27.0 } } });
  assert.match(v1.sweeps["SV-RANGE"].sql, /sensor_role = 'zone_t' AND \(value < \(19\.5 - 7\.5 \* 1\)/);
  assert.equal(v1.ruleHashes["SV-RANGE"], sha(v1.sweeps["SV-RANGE"].sql));
  const other = t.forEquip("s", "VAV-2");
  assert.equal(other.configRevision, 3, "site revision for equipment without its own");
  assert.match(other.sweeps["SV-RANGE"].sql, /\(21\.0 - 9\.0 \* 1\)/);
  assert.equal(t.forEquip("s", "VAV-RESET").configRevision, 3, "an equipment reset falls back to the site layer");
  assert.equal(t.forEquip("s", "VAV-BAD"), null, "an override that no longer validates is skipped ...");
  assert.ok(logs.some((m) => /VAV-BAD: role-limit override not applied/.test(m)), "... loudly");
  assert.equal(t.summary.errors.length, 1);
  assert.equal(t.forEquip("other-site", "VAV-1"), null);
});

test("tuning hook: argument checks and a clear answer without Timescale", async () => {
  assert.throws(() => tuningHook.parseArgs({ action: "drop" }), /action must be one of/);
  assert.throws(() => tuningHook.parseArgs({ scope: "building" }), /scope must be/);
  assert.deepEqual(tuningHook.parseArgs({ action: "rollback", revision: "3", scope: "equip:AHU-1", site: "s", overrides: '{"version":1,"roles":{}}' }),
    { action: "rollback", site: "s", scope: "equip:AHU-1", overrides: { version: 1, roles: {} }, revision: 3, by: "open-fdd-ui", note: undefined });
  const logs = [];
  const out = await tuningHook.handle({ sdk: { logEvent: (m) => logs.push(m) }, args: { action: "get" }, config: {} });
  assert.equal(out.ok, false);
  assert.match(out.error, /timescale/);
  assert.equal(JSON.parse(logs.at(-1)).ok, false, "the answer is the run's last event (the editor reads it)");
});
