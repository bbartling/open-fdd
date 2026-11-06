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

/** Points (from `pool`) that fill each role, best match first (class before markers). */
function bindRoles(roles, pool, catalog) {
  const out = {};
  for (const role of roles) {
    const def = catalog.roles[role];
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
