// Rule ↔ point binding for the Open-FDD NF app. Uses fdd-catalog.json (built by
// scripts/nf/build_rule_catalog.py from sql/fdd/registry.yaml + role_map.json + NF classes).
// A point fills a role if its NF class is listed for the role, or else it carries every
// marker of the role. Nothing site-specific: equipment kinds come from equip markers.
// Needs model.js (has, markersOf, idOf). The FDD hook uses the same rules (slice 3).

/** Equipment kinds (ahu, vav, chiller, …) an equip record has, from its Haystack markers. */
/** @param {NfRecord} equipRec @param {FddCatalog} catalog @returns {string[]} */
function equipKinds(equipRec, catalog) {
  const markers = new Set(markersOf(equipRec));
  return Object.entries(catalog.equipment_kinds)
    .filter(([, ms]) => ms.some((m) => markers.has(m)))
    .map(([kind]) => kind);
}

const isWebRole = (role) => role.startsWith("web_");

/** How well point `p` fills role `role` (0 = not at all; higher = better). */
function roleScore(p, role, def) {
  // Weather-service points only fill web_* roles; equipment sensors never do.
  if (isWebRole(role) !== has(p, "weather")) return 0;
  if (p.cls && def.classes.includes(p.cls)) return 2;
  return def.markers.length > 0 && def.markers.every((m) => p.tags.includes(m)) ? 1 : 0;
}

const fillsRole = (p, role, def) => roleScore(p, role, def) > 0;

/**
 * Roles only the RCx charts use (no FDD rule reads them, so they are not in the rule catalog or the SQL input contract):
 * the DX cooling proof an AHU / RTU can carry for the mechanical-cooling hours chart (the pandas DX_RUN_ROLES set).
 * Bound by Haystack markers exactly like a catalog role.
 */
const FDD_EXTRA_ROLES = {
  compressor_cmd: { name: "compressor-cmd", classes: [], markers: ["compressor", "run", "cmd"], scale: "fraction" },
  dx_cool_cmd: { name: "dx-cool-cmd", classes: [], markers: ["dx", "cool", "cmd"], scale: "fraction" },
  dx_cooling: { name: "dx-cooling", classes: [], markers: ["dx", "cool", "sensor"], scale: "boolean" },
};

/** Points (from `pool`) that fill each role, best match first (class before markers). */
function bindRoles(roles, pool, catalog) {
  const out = {};
  for (const role of roles) {
    const def = catalog.roles[role] || FDD_EXTRA_ROLES[role];
    out[role] = !def ? [] : pool
      .map((p) => [roleScore(p, role, def), p])
      .filter(([s]) => s > 0)
      .sort((a, b) => b[0] - a[0] || a[1].name.localeCompare(b[1].name))
      .map(([, p]) => p);
  }
  return out;
}

/**
 * Every rule that applies to one equip, with its inputs bound:
 * { rule, required, optional, bound: {role: [points]}, missing: [roles], runnable, pointInputs }
 * Pool = the equip's tagged points + the site's weather points (for web_* roles).
 * pointInputs = false when a rule has no required role and no optional input bound (it reads other data).
 */
/** Points an equip's roles may bind to: its own tagged points + its site's weather points. */
function equipPool(equipRec, model) {
  const eid = idOf(equipRec);
  const siteRef = (equipRec.attrs || {}).siteRef;
  // Equip ids are only unique within a site: a point belongs to this equip only if both its
  // equipRef and its siteRef match (GitHub #1538: never bind across sites).
  const sameSite = (p) => !siteRef || p.siteRef === siteRef;
  return model.points.filter((p) => has(p, "point") && sameSite(p) && (p.equipRef === eid || has(p, "weather")));
}

function equipRules(equipRec, model, catalog) {
  const pool = equipPool(equipRec, model);
  const kinds = new Set(equipKinds(equipRec, catalog));
  const out = [];
  for (const rule of catalog.rules) {
    const applies = !rule.equipment_kinds.length || rule.equipment_kinds.some((k) => kinds.has(k));
    if (!applies) continue;
    const required = [...new Set(rule.required_roles)];
    const optional = [...new Set(rule.optional_roles)].filter((r) => !required.includes(r));
    const bound = bindRoles([...required, ...optional], pool, catalog);
    const missing = required.filter((r) => !bound[r].length);
    // Rules with only optional roles (SV-* sensor checks) run on whichever inputs are bound;
    // with none bound (utility interval / monthly on a site without meters) they read other data.
    const pointInputs = required.length > 0 || optional.some((r) => bound[r].length > 0);
    out.push({ rule, required, optional, bound, missing, pointInputs, runnable: pointInputs && missing.length === 0 });
  }
  return out.sort((a, b) => b.runnable - a.runnable || b.pointInputs - a.pointInputs
    || a.missing.length - b.missing.length || a.rule.id.localeCompare(b.rule.id));
}

/** @type {FddCatalog | null} */
let fddCatalog = null;
async function loadCatalog() {
  if (!fddCatalog) {
    const r = await fetch("fdd-catalog.json", { credentials: "same-origin" });
    if (!r.ok) throw new Error(`fdd-catalog.json → HTTP ${r.status}`);
    fddCatalog = await r.json();
  }
  return fddCatalog;
}

// ---- rule labels: the title first, the id as a distinct "rule" badge -----------------------
// A rule id such as "VAV-1" reads like an equipment called VAV 1, so wherever a rule is named the
// human title leads and the id sits in a monospace badge with a small "rule" prefix (CSS .rule-badge).

/** Short human title of a catalog rule: the first clause of its description, at most 64 characters. */
/** @param {{id?: string, description?: string}} rule */
function fddRuleTitle(rule) {
  const d = String((rule && rule.description) || "").trim();
  const clause = d.split(/\s+[—–-]\s+|;|\. |:|â†’|→/)[0].trim() || d;
  const t = clause.length > 64 ? `${clause.slice(0, 61).trimEnd()}...` : clause;
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : String((rule && rule.id) || "");
}

/** Catalog rule by id (or a bare { id } when unknown). */
const fddRuleOf = (catalog, id) => ((catalog && catalog.rules) || []).find((r) => r.id === id) || { id, description: "" };

const fddEsc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

/** HTML badge for a rule id: <span class="rule-badge"><i>rule</i><span class="rule-id">VAV-1</span></span>. */
const fddRuleBadgeHtml = (id) => `<span class="rule-badge"><i>rule</i><span class="rule-id">${fddEsc(id)}</span></span>`;

/** HTML for a rule cell: title first, then the badge. */
const fddRuleCellHtml = (rule) => `<span class="rule-title">${fddEsc(fddRuleTitle(rule))}</span> ${fddRuleBadgeHtml(rule.id)}`;

/** Rich-text styles for chart text (axis labels, titles) that carries a rule badge: {t|Title} {b|rule ID}. */
const FDD_RULE_RICH = {
  t: { fontWeight: 600 },
  b: { fontFamily: "ui-monospace, Consolas, monospace", fontSize: 11, color: "#7c3aed", backgroundColor: "rgba(124,58,237,0.12)",
    borderRadius: 3, padding: [1, 5], },
  e: { color: "#64748b" },
};
/** ECharts rich text: "Title  [rule ID]  · equip" (equip optional). */
const fddRuleRich = (title, id, equip = "") => `{t|${title}} {b|rule ${id}}${equip ? ` {e|· ${equip}}` : ""}`;

// ---- FDD tab state: one equip filter + the heat map's row limit -----------------------------
/** "" = all equipment. heatAll = show every heat-map row instead of the most-faulted FDD_HEAT_TOP_N. */
const fddUi = { equip: "", heatAll: false };

/** Heat map rows shown by default: the most-faulted rules (sorted by fault time), not every rule x equip. */
const FDD_HEAT_TOP_N = 12;

/**
 * Rows of the fault heat map. rows = [{ key, faultTime }] (faultTime = summed fault output over the range).
 *   - an equip is selected (selectedEquip non-empty): every row of that equip, "which faults happen most" order;
 *   - no equip and !showAll: only the top N rows by fault time (a short list is shown whole, assessed-zero rows included);
 *   - showAll: all rows, same order.
 * Sorted by faultTime descending, ties by key. Returns { rows, total, trimmed }.
 */
function fddHeatRows(rows, { selectedEquip = "", showAll = false, topN = FDD_HEAT_TOP_N, equipOf = (r) => r.equip } = {}) {
  const sorted = [...rows].sort((a, b) => (b.faultTime || 0) - (a.faultTime || 0) || String(a.key).localeCompare(String(b.key)));
  const scoped = selectedEquip ? sorted.filter((r) => equipOf(r) === selectedEquip) : sorted;
  if (selectedEquip || showAll) return { rows: scoped, total: scoped.length, trimmed: false };
  const kept = scoped.slice(0, topN);
  return { rows: kept, total: scoped.length, trimmed: kept.length < scoped.length };
}

/** Equip options for a tab picker: [{ id, label }] sorted by label, from the site's equip records. */
function fddEquipOptions(model, site, kinds = null, catalog = null) {
  return model.equips
    .filter((e) => (e.attrs || {}).siteRef === site && (!kinds || !catalog || equipKinds(e, catalog).some((k) => kinds.includes(k))))
    .map((e) => ({ id: idOf(e), label: (e.attrs || {}).dis || e.name }))
    .sort((a, b) => a.label.localeCompare(b.label));
}
