// Plot spec v1 producer (JS twin of open_fdd/plot_spec.py): which series and fault strips a plot shows, chosen from the
// Haystack model only. Returns a plain object naming points, never values; a renderer fetches values for point_uuid + window
// and draws them in SI, converting for display only (units.json). toJson() emits canonical JSON that is byte-identical to the
// Python producer's for the same model (tests/fixtures/plot_spec/golden).
//
// Selection follows fdd.js: NF class = score 2, marker set = score 1, weather points fill only web_* roles. No point names,
// name regexes or role-to-key maps. Rule ids may be matched by family (SV-* sweeps, ECON-*): rule ids are part of the contract.
//
//   ofddPlotSpec.buildRuleSpec(model, ruleId, equip, { from, to }, { tz, catalog })
//   ofddPlotSpec.buildPresetSpec(model, presetId, equips, { from, to }, { tz, catalog })   // equips of one site
//   ofddPlotSpec.toJson(spec)
//
// Data (rcx_presets.json, units.json, palette.json) comes from plot-spec-data.js, generated from open_fdd/data by
// scripts/nf/build_plot_spec_data.py. The catalog (fdd-catalog.json) is passed in, as for fdd.js.
// Classic script (global `ofddPlotSpec`) and CommonJS from one file; not loaded by any page yet.
(function (root) {
  "use strict";

  const SPEC_VERSION = 1;
  const GENERIC_MARKERS = ["point", "his", "cur", "writable"];
  const WEB_ROLE_PREFIX = "web_";
  const SWEEP_RULE_PATTERN = /^SV-(RATE|RANGE|FLATLINE|SPIKE|STALE)$/;
  const ECON_RULE_PATTERN = /^ECON-[1-7]$/;
  const ECON_EXTRA_ROLE = "oa_damper_pct";
  const NAV_SEPARATOR = " › ";
  const COLOR_KEYS = 12;
  const FALLBACK_TZ = "UTC";

  /** @returns {any} */
  function data() {
    const d = root.ofddPlotSpecData || (typeof require === "function" ? require("./plot-spec-data.js") : null);
    if (!d) throw new Error("plot-spec.js needs plot-spec-data.js (ofddPlotSpecData) loaded first");
    return d;
  }

  let registryCache = null, unitsCache = null;
  function registry() {
    if (!registryCache) {
      const presets = data().presets.presets, byId = new Map(), alias = new Map();
      for (const p of presets) { byId.set(p.id, p); for (const a of p.aliases || []) alias.set(a, p.id); }
      registryCache = { presets, byId, alias };
    }
    return registryCache;
  }

  /** Same normalisation as units.js: trim, lower-case, drop whitespace and underscores. */
  const normUnit = (unit) => String(unit == null ? "" : unit).trim().toLowerCase().replace(/[\s_]/g, "")
    .split("₂").join("2").split("º").join("°");

  function units() {
    if (!unitsCache) {
      const doc = data().units, index = new Map();
      for (const row of doc.aliases) for (const name of row.names) index.set(normUnit(name), row);
      unitsCache = { doc, index };
    }
    return unitsCache;
  }

  const presetIds = () => registry().presets.map((p) => p.id);
  function resolvePresetId(presetId) {
    const reg = registry();
    if (reg.byId.has(presetId)) return presetId;
    if (reg.alias.has(presetId)) return reg.alias.get(presetId);
    throw new Error(`unknown plot preset ${JSON.stringify(presetId)}`);
  }

  // ---- small helpers (ports of model.js / fdd.js) ---------------------------------------------------
  const attrsOf = (rec) => (rec && rec.attrs) || {};
  const idOf = (rec) => attrsOf(rec).id || rec.name || "";
  const markersOf = (rec) => String(attrsOf(rec).markers || "").split(",").filter(Boolean);
  const has = (p, ...m) => m.every((x) => (p.tags || []).includes(x));
  const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

  function equipKinds(equipRec, catalog) {
    const markers = new Set(markersOf(equipRec));
    return Object.entries(catalog.equipment_kinds).filter(([, ms]) => ms.some((m) => markers.has(m))).map(([k]) => k);
  }

  const isWebRole = (role) => role.startsWith(WEB_ROLE_PREFIX);

  function roleScore(p, role, def) {
    if (isWebRole(role) !== has(p, "weather")) return 0;
    if (p.cls && def.classes.includes(p.cls)) return 2;
    return def.markers.length > 0 && def.markers.every((m) => (p.tags || []).includes(m)) ? 1 : 0;
  }

  const pointOrder = (a, b) => b[0] - a[0] || cmp(String(a[1].name || ""), String(b[1].name || "")) || cmp(String(a[1].uuid || ""), String(b[1].uuid || ""));

  function bindRoles(roles, pool, catalog) {
    const out = {};
    for (const role of roles) {
      const def = catalog.roles[role];
      out[role] = !def ? [] : pool.map((p) => [roleScore(p, role, def), p]).filter(([s]) => s > 0).sort(pointOrder).map(([, p]) => p);
    }
    return out;
  }

  function equipPool(equipRec, model) {
    const eid = idOf(equipRec), siteRef = attrsOf(equipRec).siteRef;
    return model.points.filter((p) => has(p, "point") && (!siteRef || p.siteRef === siteRef) && (p.equipRef === eid || has(p, "weather")));
  }

  function markerPoints(selector, equipRec, model) {
    const eid = idOf(equipRec), siteRef = attrsOf(equipRec).siteRef;
    const anyOf = selector.any_of || [], exclude = selector.exclude || [];
    return model.points.filter((p) => has(p, "point") && p.equipRef === eid && (!siteRef || p.siteRef === siteRef)
      && has(p, ...selector.markers) && (!anyOf.length || anyOf.some((m) => has(p, m))) && !exclude.some((m) => has(p, m)))
      .map((p) => [1, p]).sort(pointOrder).map(([, p]) => p);
  }

  function findSite(model, siteRef) {
    const sites = model.sites || [];
    const hit = sites.find((s) => idOf(s) === siteRef);
    if (hit) return hit;
    return sites.length === 1 && !siteRef ? sites[0] : null;
  }

  function resolveEquip(model, equip) {
    if (equip && typeof equip === "object") return equip;
    let found = (model.equips || []).filter((e) => e.uuid === equip);
    if (!found.length) found = (model.equips || []).filter((e) => idOf(e) === equip);
    if (found.length !== 1) throw new Error(`equip ${JSON.stringify(equip)} matches ${found.length} records in the model; pass the equip record or its uuid`);
    return found[0];
  }

  // ---- window, site, ids ----------------------------------------------------------------------------
  function isoUtc(value) {
    let ms;
    if (value instanceof Date) ms = value.getTime();
    else if (typeof value === "number") ms = value;
    else {
      let text = String(value).trim();
      if (!/(Z|[+-]\d{2}:?\d{2})$/i.test(text)) text += "Z";
      ms = Date.parse(text);
    }
    if (!Number.isFinite(ms)) throw new Error(`bad window time ${JSON.stringify(value)}`);
    return new Date(ms).toISOString().replace(".000Z", "Z");
  }

  function windowOf(w) {
    const from = isoUtc(w.from), to = isoUtc(w.to);
    if (to < from) throw new Error("window.to is before window.from");
    return { from, to };
  }

  function siteBlock(model, equipRec, tz) {
    const siteRef = attrsOf(equipRec).siteRef || "";
    const site = findSite(model, siteRef);
    const own = site ? (attrsOf(site).tz || attrsOf(site).timezone) : null;
    let zone, source;
    if (own) { zone = own; source = "model"; } else if (tz) { zone = tz; source = "option"; } else { zone = FALLBACK_TZ; source = "fallback"; }
    return { ref: siteRef || (site ? idOf(site) : ""), tz: zone, tz_source: source };
  }

  /** FNV-1a 32-bit of the UTF-8 bytes of the point uuid, modulo 12. */
  function colorKey(pointUuid) {
    let h = 0x811c9dc5;
    for (const byte of new TextEncoder().encode(String(pointUuid))) {
      h ^= byte;
      h = Math.imul(h, 0x01000193) >>> 0;
    }
    return h % COLOR_KEYS;
  }

  // ---- units ----------------------------------------------------------------------------------------
  function quantityFor(p, roleDef) {
    const U = units(), doc = U.doc, unit = p.units || "";
    if (unit) {
      const row = U.index.get(normUnit(unit));
      if (!row) return null;
      let quantity = row.quantity;
      const refine = doc.refine[quantity];
      if (refine) quantity = has(p, refine.marker) ? refine.yes : refine.no;
      return quantity;
    }
    if (p.kind === "Bool") return "boolean";
    const scale = roleDef && roleDef.scale;
    return scale ? (doc.role_scales[scale] || null) : null;
  }

  function seriesKind(p, roleDef) {
    if (has(p, "weather")) return "weather";
    if (has(p, "sp")) return "sp";
    if (has(p, "cmd")) return "cmd";
    if (p.kind === "Bool" || has(p, "status") || (roleDef && roleDef.scale === "boolean")) return "status";
    return "sensor";
  }

  function seriesRow(p, role, roleDef, equipRec, siteDis, required) {
    const quantity = quantityFor(p, roleDef);
    if (quantity == null) return null;
    const q = units().doc.quantities[quantity], kind = seriesKind(p, roleDef);
    const owner = kind === "weather" || !equipRec ? null : equipRec;
    const ownerDis = owner === null ? siteDis : (attrsOf(owner).dis || owner.name || "");
    return {
      point_uuid: p.uuid,
      equip_uuid: owner === null ? null : owner.uuid,
      role,
      dis: p.dis || "",
      nav: `${ownerDis}${NAV_SEPARATOR}${p.dis || ""}`,
      tags: (p.tags || []).filter((t) => !GENERIC_MARKERS.includes(t)),
      class: p.cls || null,
      quantity,
      unit_si: q.si,
      kind,
      axis: q.axis,
      color_key: colorKey(p.uuid),
      required: !!required,
    };
  }

  // ---- fault strips (ports of rcx.js rcxMatchRank / rcxBestPoint) -------------------------------------
  const equipIdentity = (rec) => ({ id: idOf(rec), site: attrsOf(rec).siteRef || "", uuid: rec.uuid || "" });

  function matchRank(p, who, model) {
    if (p.equipRef !== who.id) return 0;
    const a = attrsOf(p.rec);
    if (who.uuid && a.equipUuid) return a.equipUuid === who.uuid ? 3 : 0;
    if (!who.site) return 1;
    if (p.siteRef) return p.siteRef === who.site ? 2 : 0;
    return (model.equips || []).filter((e) => idOf(e) === who.id).length <= 1 ? 1 : 0;
  }

  function bestPoint(model, equipRec, ruleId, markers, sensorRef) {
    const who = equipIdentity(equipRec);
    let best = null, bestRank = 0;
    for (const p of model.points) {
      const a = attrsOf(p.rec);
      if (!has(p, ...markers) || String(a.ruleRef || "") !== ruleId) continue;
      if (sensorRef !== null && String(a.sensorRef || "") !== String(sensorRef)) continue;
      if (sensorRef === null && a.sensorRef) continue;
      const rank = matchRank(p, who, model);
      if (rank > bestRank) { best = p; bestRank = rank; }
    }
    return best;
  }

  function strip(model, equipRec, ruleId, sensorUuid) {
    const timeline = bestPoint(model, equipRec, ruleId, ["fault_timeline"], sensorUuid);
    let pointUuid = null, source = "intervals", approximate = false;
    if (timeline) { pointUuid = timeline.uuid; source = "timeline"; } else {
      const result = bestPoint(model, equipRec, ruleId, ["fdd", "fault"], sensorUuid);
      if (result) { pointUuid = result.uuid; source = "fault_pct"; approximate = true; }
    }
    return { rule_id: ruleId, equip_uuid: equipRec.uuid, point_uuid: pointUuid, sensor_uuid: sensorUuid, source, approximate };
  }

  function sensorResultPoints(model, equipRec, ruleId) {
    const who = equipIdentity(equipRec);
    return model.points.filter((p) => {
      const a = attrsOf(p.rec);
      return has(p, "fdd", "fault") && String(a.ruleRef || "") === ruleId && (a.fddSummary === "sensor" || a.sensorRef) && matchRank(p, who, model) > 0;
    });
  }

  // ---- builders -------------------------------------------------------------------------------------
  function finish(kind, ruleId, presetId, site, equips, win, series, strips, missing, reason, catalog) {
    const miss = [...missing.values()].sort((a, b) => cmp(a.role, b.role) || cmp(a.reason, b.reason));
    return {
      spec_version: SPEC_VERSION, kind, rule_id: ruleId, preset_id: presetId, site,
      equip: equips.map((e) => ({ uuid: e.uuid, ref: idOf(e), dis: attrsOf(e).dis || e.name || "", kind: equipKinds(e, catalog)[0] || "" })),
      window: win, series, fault_strips: strips, missing: miss, selection_reason: reason,
    };
  }

  const addMissing = (set, role, reason) => set.set(`${role}\u0000${reason}`, { role, reason });

  /**
   * Plot spec for one FDD rule on one equip. `opts.catalog` = fdd-catalog.json (default: the page's loaded catalog).
   * @param {any} model @param {string} ruleId @param {any} equip @param {{from: any, to: any}} window @param {{tz?: string, catalog?: any}} [opts]
   */
  function buildRuleSpec(model, ruleId, equip, window, opts = {}) {
    const catalog = opts.catalog || (typeof fddCatalog !== "undefined" ? fddCatalog : null);
    if (!catalog) throw new Error("buildRuleSpec needs opts.catalog (fdd-catalog.json)");
    const rule = catalog.rules.find((r) => r.id === ruleId);
    if (!rule) throw new Error(`unknown FDD rule ${JSON.stringify(ruleId)}`);
    const equipRec = resolveEquip(model, equip), site = siteBlock(model, equipRec, opts.tz), win = windowOf(window);
    const kinds = equipKinds(equipRec, catalog), wantedKinds = rule.equipment_kinds || [];
    if (wantedKinds.length && !wantedKinds.some((k) => kinds.includes(k))) {
      return finish("rule", ruleId, null, site, [equipRec], win, [], [], new Map(),
        `rule ${ruleId} does not apply to equip kind ${kinds[0] || "none"}`, catalog);
    }
    const required = [...new Set(rule.required_roles || [])];
    const optional = [...new Set(rule.optional_roles || [])].filter((r) => !required.includes(r));
    const roles = [...required, ...optional];
    const bound = bindRoles([...roles, ECON_EXTRA_ROLE], equipPool(equipRec, model), catalog);
    if (ECON_RULE_PATTERN.test(String(ruleId).trim().toUpperCase()) && !roles.includes(ECON_EXTRA_ROLE) && bound[ECON_EXTRA_ROLE].length) roles.push(ECON_EXTRA_ROLE);
    const sweep = SWEEP_RULE_PATTERN.test(String(ruleId));
    const siteSite = findSite(model, site.ref), siteDis = attrsOf(siteSite).dis || site.ref;
    const series = [], seen = new Set(), missing = new Map();
    const add = (p, role, isRequired) => {
      if (seen.has(p.uuid)) return;
      seen.add(p.uuid);
      const row = seriesRow(p, role, catalog.roles[role], equipRec, siteDis, isRequired);
      if (row === null) addMissing(missing, role, "unit_unusable"); else series.push(row);
    };
    for (const role of roles) for (const p of (sweep ? bound[role] : bound[role].slice(0, 1))) add(p, role, required.includes(role));
    if (sweep) {
      const byUuid = new Map(model.points.filter((p) => has(p, "point")).map((p) => [p.uuid, p]));
      for (const result of sensorResultPoints(model, equipRec, ruleId)) {
        const a = attrsOf(result.rec), sensor = byUuid.get(String(a.sensorRef || ""));
        if (sensor) add(sensor, a.roleRef || "sensor", false);
      }
    }
    for (const role of required) if (!bound[role].length) addMissing(missing, role, "unbound");
    const strips = sweep ? series.map((s) => strip(model, equipRec, ruleId, s.point_uuid)) : [strip(model, equipRec, ruleId, null)];
    const boundN = roles.filter((r) => bound[r].length).length;
    return finish("rule", ruleId, null, site, [equipRec], win, series, strips, missing,
      `rule inputs ${ruleId}: ${boundN} of ${roles.length} roles bound by class/markers`, catalog);
  }

  /**
   * Plot spec for a registry preset over equips of one site (one spec per site).
   * @param {any} model @param {string} presetId @param {any[]} equips @param {{from: any, to: any}} window @param {{tz?: string, catalog?: any}} [opts]
   */
  function buildPresetSpec(model, presetId, equips, window, opts = {}) {
    const catalog = opts.catalog || (typeof fddCatalog !== "undefined" ? fddCatalog : null);
    if (!catalog) throw new Error("buildPresetSpec needs opts.catalog (fdd-catalog.json)");
    const canonical = resolvePresetId(presetId), preset = registry().byId.get(canonical);
    const recs = [...equips].map((e) => resolveEquip(model, e)).sort((a, b) =>
      cmp(attrsOf(a).dis || a.name || "", attrsOf(b).dis || b.name || "") || cmp(idOf(a), idOf(b)) || cmp(a.uuid || "", b.uuid || ""));
    if (!recs.length) throw new Error("buildPresetSpec needs at least one equip");
    if (new Set(recs.map((e) => attrsOf(e).siteRef || "")).size > 1) throw new Error("a plot spec covers one site: build one spec per site");
    const site = siteBlock(model, recs[0], opts.tz), win = windowOf(window);
    const siteDis = attrsOf(findSite(model, site.ref)).dis || site.ref;
    const kindsWanted = preset.equip_kinds, selectors = preset.series, skip = preset.skip_equip_if_bound || [];
    const qualifying = [], missing = new Map();
    for (const rec of recs) {
      const kinds = equipKinds(rec, catalog);
      if (kindsWanted.length && !kindsWanted.some((k) => kinds.includes(k))) continue;
      const bound = bindRoles(selectors.filter((s) => "role" in s).map((s) => s.role), equipPool(rec, model), catalog);
      const found = [], unbound = [];
      for (const sel of selectors) {
        const points = "role" in sel ? bound[sel.role] : markerPoints(sel, rec, model);
        if (sel.required && !points.length) unbound.push("role" in sel ? sel.role : `marker:${sel.markers.join(",")}`);
        found.push([sel, points]);
      }
      if (unbound.length) { for (const r of unbound) addMissing(missing, r, "unbound"); continue; }
      if (skip.some((r) => (bound[r] || []).length)) continue;
      qualifying.push([rec, found]);
    }
    const series = [], strips = [], used = [];
    let reason;
    if (qualifying.length >= preset.min_equips) {
      const seen = new Set();
      let boundSelectors = 0;
      for (const [rec, found] of qualifying) {
        used.push(rec);
        for (const [sel, points] of found) {
          if (points.length) boundSelectors++;
          const role = "role" in sel ? sel.role : `marker:${sel.markers.join(",")}`;
          for (const p of (sel.multiple ? points : points.slice(0, 1))) {
            if (seen.has(p.uuid)) continue;
            seen.add(p.uuid);
            const row = seriesRow(p, role, "role" in sel ? catalog.roles[sel.role] : undefined, rec, siteDis, !!sel.required);
            if (row === null) addMissing(missing, role, "unit_unusable"); else series.push(row);
          }
        }
        for (const ruleId of preset.fault_rules) strips.push(strip(model, rec, ruleId, null));
      }
      reason = `preset ${canonical}: ${qualifying.length} of ${recs.length} equips qualify, ${boundSelectors} of ${qualifying.length * selectors.length} series selectors bound by class/markers`;
    } else {
      reason = `preset ${canonical}: ${qualifying.length} of ${recs.length} equips qualify, fewer than the ${preset.min_equips} it needs`;
    }
    return finish("preset", null, canonical, site, used, win, series, strips, missing, reason, catalog);
  }

  // ---- canonical JSON -------------------------------------------------------------------------------
  const sortKeys = (v) => (Array.isArray(v) ? v.map(sortKeys)
    : v && typeof v === "object" ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, sortKeys(v[k])])) : v);

  /** Canonical JSON: sorted keys, no whitespace, non-ASCII kept (same bytes as open_fdd.plot_spec.to_json). */
  const toJson = (spec) => JSON.stringify(sortKeys(spec));

  const api = { SPEC_VERSION, buildRuleSpec, buildPresetSpec, colorKey, normUnit, presetIds, resolvePresetId, toJson };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.ofddPlotSpec = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
