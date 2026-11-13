// Per-rule SQL parameter tuning & inline FDD Tuners tests (5.0.17).
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import vm from "node:vm";

const require = createRequire(import.meta.url);
const RT = require("../hooks/lib/rule-tuning.js");
const RL = require("../hooks/lib/role-limits.js");
const tuning = require("../static/tuning.js");
const tuningHook = require("../hooks/tuning.js");
const fddHook = require("../hooks/fdd.js");
const pack = JSON.parse(readFileSync(new URL("../rules/pack-postgres.json", import.meta.url), "utf8"));
const catalog = JSON.parse(readFileSync(new URL("../static/fdd-catalog.json", import.meta.url), "utf8"));
const plotSpecData = (() => {
  const ctx = vm.createContext({});
  vm.runInContext(readFileSync(new URL("../static/plot-spec-data.js", import.meta.url), "utf8"), ctx);
  return ctx.ofddPlotSpecData;
})();

test("shared/rule-tuning.js syncs identically to hooks/lib/rule-tuning.js and static/rule-tuning.js", () => {
  const body = (p) => readFileSync(new URL(p, import.meta.url), "utf8").split("\n").slice(1).join("\n");
  assert.equal(body("../hooks/lib/rule-tuning.js"), body("../static/rule-tuning.js"));
});

test("pack rule_tuning_templates and plot-spec-data rule_tuning are clean (zero SQL in browser)", () => {
  assert.ok(pack.rule_tuning_templates && pack.rule_tuning_templates.rules);
  assert.ok(plotSpecData.rule_tuning && plotSpecData.rule_tuning.rules);
  for (const [rid, r] of Object.entries(plotSpecData.rule_tuning.rules)) {
    assert.equal(r.sql, undefined, `${rid} browser metadata must not ship SQL`);
    assert.equal(r.timeline_sql, undefined, `${rid} browser metadata must not ship timeline SQL`);
  }
});

test("JS renderRuleSql matches Python sql/fdd/render_rule.py byte-for-byte with overrides", () => {
  const root = new URL("../..", import.meta.url).pathname;
  const pyBin = process.env.OPENFDD_PYTHON || "python3";
  const cases = [
    { ruleId: "VAV-1", params: { confirm_min: 15, zone_t_hi: 26.5, require_occupied: 0 } },
    { ruleId: "FC1", params: { eps_dsp: 75, confirm_min: 20 } },
    { ruleId: "ECON-4", params: { oa_min_pct: 25, oat_rat_delta_min: 1.5 } },
    { ruleId: "FC2", params: { mix_tol: 1.8, eps_mat: 1.2 } },
    { ruleId: "OAT-METEO", params: { oat_err: 3.5, web_asof_margin_seconds: 900 } },
    { ruleId: "CHW-4", params: { confirm_min: 10 } },
    { ruleId: "SV-RANGE", params: { range_scale_humidity: 1.15, max_silence_hours: 12 } },
  ];
  const tplRoot = pack.rule_tuning_templates;
  for (const c of cases) {
    const pyScript = `import json, os, sys; sys.path.insert(0, ${JSON.stringify(root)}); sys.path.insert(0, os.path.join(${JSON.stringify(root)}, "scripts", "nf")); from sql.fdd.render_rule import render; from build_sql_pack import build_timeline_pg; sql = render(${JSON.stringify(c.ruleId)}, overrides=${JSON.stringify(c.params)}); tl = build_timeline_pg(sql) if ${tplRoot.rules[c.ruleId].timeline_sql ? "True" : "False"} else None; print(json.dumps({"sql": sql, "timeline_sql": tl}))`;
    let pyOut;
    pyOut = JSON.parse(execFileSync(pyBin, ["-c", pyScript], { encoding: "utf8" }));
    const ruleTpl = tplRoot.rules[c.ruleId];
    const merged = RT.mergeRuleParams(ruleTpl.controls, { version: 1, params: c.params }, null, c.ruleId);
    const values = RT.resolvePlaceholders(tplRoot.runtime_defaults, ruleTpl.controls, merged.effective, merged.overrideKeys, pack.poll_seconds);
    let roleLimitsOpt = null;
    if (RL.SWEEP_RULES.includes(c.ruleId)) {
      roleLimitsOpt = {
        roleTemplate: pack.role_limit_templates.rules[c.ruleId],
        limits: RL.effectiveRoleLimits(pack.role_limit_templates.shipped, pack.role_limit_templates.allowlists),
        fillTemplate: RL.fillTemplate,
      };
    }
    const jsSql = RT.renderRuleSql(ruleTpl.sql, values, c.ruleId, roleLimitsOpt);
    const jsTl = RT.renderRuleSql(ruleTpl.timeline_sql, values, c.ruleId, roleLimitsOpt);
    assert.equal(jsSql, pyOut.sql, `${c.ruleId} SQL mismatch`);
    assert.equal(jsTl, pyOut.timeline_sql, `${c.ruleId} timeline_sql mismatch`);
  }
});

test("inline Tuners: sweep filtering, scoped merge, per-rule reset & rollback preserve sibling fields", () => {
  assert.deepEqual(tuning.sweepFieldsForRule("SV-RANGE"), ["lo", "hi"]);
  assert.deepEqual(tuning.sweepFieldsForRule("SV-SPIKE"), ["spike_delta"]);
  assert.deepEqual(tuning.sweepFieldsForRule("VAV-1"), []);

  const bound = {
    zone_t: [{ uuid: "p1" }],
    sat: [{ uuid: "p2" }],
    oa_t: [],
  };
  assert.deepEqual(tuning.assessableSweepRoles(bound, catalog), ["zone-air-temp", "discharge-air-temp"]);

  const existing = {
    version: 1,
    roles: {
      "zone-air-temp": { lo: 12, hi: 28, spike_delta: 4.5 },
      "discharge-air-temp": { lo: 8, spike_delta: 6.0 },
    },
  };
  const clearedRange = tuning.resetSweepOverrideForRule(existing, ["lo", "hi"], ["zone-air-temp"]);
  assert.deepEqual(clearedRange.roles, {
    "zone-air-temp": { spike_delta: 4.5 },
    "discharge-air-temp": { lo: 8, spike_delta: 6.0 },
  });

  const targetRev = {
    version: 1,
    roles: {
      "zone-air-temp": { lo: 15, hi: 26, spike_delta: 9.9 },
      "outside-air-temp": { lo: -30, hi: 45 },
    },
  };
  const rolledRange = tuning.rollbackSweepOverrideForRule(targetRev, existing, ["lo", "hi"], ["zone-air-temp"]);
  assert.deepEqual(rolledRange.roles, {
    "zone-air-temp": { spike_delta: 4.5, lo: 15, hi: 26 },
    "discharge-air-temp": { lo: 8, spike_delta: 6.0 },
  });
});

test("buildRuleOverride converts imperial inputs to SI and rejects out-of-range without silent clamping", () => {
  const controls = plotSpecData.rule_tuning.rules["VAV-1"].controls;
  const merged = RT.mergeRuleParams(controls, null, null, "VAV-1");
  const ov = tuning.buildRuleOverride(
    { zone_t_hi: { text: "77", unit: "degF" }, require_occupied: { checked: false } },
    controls,
    merged.effective,
    null,
    "imperial",
    "VAV-1",
  );
  assert.deepEqual(ov.params, { zone_t_hi: 25, require_occupied: 0 });
  assert.throws(
    () => tuning.buildRuleOverride({ zone_t_hi: { text: "999", unit: "degF" } }, controls, merged.effective, null, "imperial", "VAV-1"),
    /outside/,
  );
});

test("hooks/tuning.js handles per-rule get/preview/save/conflict/rollback and keeps preview read-only", async () => {
  const store = [];
  let revSeq = 0;
  const mockClient = {
    async query(sql, params = []) {
      const s = String(sql);
      if (s.includes("to_regclass('fdd.point')")) return { rows: [{ ok: true }] };
      if (s.includes("pg_advisory_xact_lock")) return { rows: [] };
      if (s.includes("SELECT site_id, rule_id, scope_key, revision, parameters FROM fdd.rule_config")) {
        const [rid, site] = params;
        return { rows: store.filter((r) => (!rid || r.rule_id === rid) && (!site || r.site_id === site) && r.active) };
      }
      if (s.includes("SELECT revision FROM fdd.rule_config") && s.includes("AND active")) {
        const [site, rid, scope] = params;
        return { rows: store.filter((r) => r.site_id === site && r.rule_id === rid && r.scope_key === scope && r.active) };
      }
      if (s.includes("SELECT parameters FROM fdd.rule_config")) {
        const [site, rid, scope, rev] = params;
        return { rows: store.filter((r) => r.site_id === site && r.rule_id === rid && r.scope_key === scope && r.revision === rev) };
      }
      if (s.includes("FROM fdd.rule_config") && s.includes("ORDER BY revision DESC LIMIT")) {
        const [site, rid, scope, lim] = params;
        return { rows: store.filter((r) => r.site_id === site && r.rule_id === rid && r.scope_key === scope).sort((a, b) => b.revision - a.revision).slice(0, lim) };
      }
      if (s.includes("coalesce(max(revision), 0) + 1 AS rev")) {
        const [site, rid, scope] = params;
        const max = store.filter((r) => r.site_id === site && r.rule_id === rid && r.scope_key === scope).reduce((m, r) => Math.max(m, r.revision), 0);
        return { rows: [{ rev: max + 1 }] };
      }
      if (s.includes("UPDATE fdd.rule_config SET active = false")) {
        const [site, rid, scope] = params;
        for (const r of store) if (r.site_id === site && r.rule_id === rid && r.scope_key === scope && r.active) r.active = false;
        return { rows: [] };
      }
      if (s.includes("INSERT INTO fdd.rule_config")) {
        const [site, rid, scope, rev, paramsJson, by] = params;
        store.push({ site_id: site, rule_id: rid, scope_key: scope, revision: rev, parameters: JSON.parse(paramsJson), created_by: by, created_at: new Date(1794528000000 + (++revSeq) * 1000), active: true });
        return { rows: [] };
      }
      if (s === "BEGIN" || s === "COMMIT" || s === "ROLLBACK") return { rows: [] };
      throw new Error(`Unexpected mock SQL: ${s}`);
    },
  };
  const call = (args) => tuningHook.handle({ sdk: { logEvent: () => {} }, args, connect: async () => mockClient, pack });

  const g0 = await call({ action: "get", site: "s1", scope: "equip:VAV-1", rule_id: "VAV-1" });
  assert.equal(g0.ok, true);
  assert.equal(g0.effective.params.confirm_min, 15);

  const prev = await call({ action: "preview", site: "s1", scope: "equip:VAV-1", rule_id: "VAV-1", overrides: { version: 1, params: { confirm_min: 18 } } });
  assert.equal(prev.ok, true);
  assert.equal(prev.written, false);
  assert.equal(store.length, 0, "preview must not write");

  const s1 = await call({ action: "save", site: "s1", scope: "equip:VAV-1", rule_id: "VAV-1", overrides: { version: 1, params: { confirm_min: 15 } }, expected_revision: 0 });
  assert.equal(s1.ok, true);
  assert.equal(s1.revision, 1);

  const conflict = await call({ action: "save", site: "s1", scope: "equip:VAV-1", rule_id: "VAV-1", overrides: { version: 1, params: { confirm_min: 20 } }, expected_revision: 0 });
  assert.equal(conflict.ok, false);
  assert.equal(conflict.code, "revision_conflict");
  assert.equal(conflict.active_revision, 1);

  const s2 = await call({ action: "save", site: "s1", scope: "equip:VAV-1", rule_id: "VAV-1", overrides: { version: 1, params: { confirm_min: 22 } }, expected_revision: 1 });
  assert.equal(s2.ok, true);
  assert.equal(s2.revision, 2);

  const rb = await call({ action: "rollback", site: "s1", scope: "equip:VAV-1", rule_id: "VAV-1", revision: 1, expected_revision: 2 });
  assert.equal(rb.ok, true);
  assert.equal(rb.revision, 3);
  assert.equal(rb.effective.params.confirm_min, 15);
});

test("hooks/fdd.js composes per-rule + SV-LIMITS overrides and isolates same revision numbers across sites", async () => {
  const rows = [
    { site_id: "site-a", rule_id: "VAV-1", scope_key: "equip:VAV-1", revision: 1, parameters: { version: 1, params: { confirm_min: 15 } } },
    { site_id: "site-b", rule_id: "VAV-1", scope_key: "equip:VAV-1", revision: 1, parameters: { version: 1, params: { confirm_min: 25 } } },
    { site_id: "site-a", rule_id: "SV-LIMITS", scope_key: "equip:VAV-1", revision: 1, parameters: { version: 1, roles: { "zone-air-temp": { lo: 12, hi: 28 } } } },
    { site_id: "site-a", rule_id: "SV-RANGE", scope_key: "equip:VAV-1", revision: 1, parameters: { version: 1, params: { max_silence_hours: 12 } } },
  ];
  const overrides = await fddHook.loadRoleLimitOverrides({
    engine: { ruleConfigOverrides: async () => rows },
    pack,
    log: () => {},
  });
  const aVav1 = overrides.forRule("site-a", "VAV-1", "VAV-1");
  const bVav1 = overrides.forRule("site-b", "VAV-1", "VAV-1");
  assert.notEqual(aVav1.sql, bVav1.sql, "same revision=1 on different sites must not collide in cache");
  assert.equal(aVav1.parameters.rule_params.effective.confirm_min, 15);
  assert.equal(bVav1.parameters.rule_params.effective.confirm_min, 25);

  const aSvRange = overrides.forRule("site-a", "VAV-1", "SV-RANGE");
  assert.ok(aSvRange.sql.includes("43200"));
  assert.equal(aSvRange.parameters.role_limits.equipment_revision, 1);
  assert.ok(aSvRange.configRevision >= 1);
  assert.ok(aSvRange.ruleHash && aSvRange.configHash);
});

test("HTML and shell: standalone Tuning tab removed, inline host present, #tuning redirects to fdd", () => {
  const html = readFileSync(new URL("../static/index.html", import.meta.url), "utf8");
  const core = readFileSync(new URL("../../shared/static/app-core.js", import.meta.url), "utf8");
  assert.ok(!/data-tab="tuning"/.test(html), "no Tuning nav button");
  assert.ok(!/id="tab-tuning"/.test(html), "no standalone tab-tuning section");
  assert.match(html, /id="fddTunersPanel"/, "inline Tuners host inside #fddPlotPanel");
  assert.match(core, /if \(name === "tuning"\) name = "fdd"/, "#tuning hash/tab redirects to fdd");
});
