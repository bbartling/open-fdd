import { apiFetch } from "./api.js";
import { displayName, GENERIC, has, isBoolRole, isRH, isTemp, roleOf, tagsOf } from "./tags.js";

export async function loadBuildingContext(buildingId) {
  const health = await apiFetch("/api/health");
  let ttl = "";
  try {
    const raw = await apiFetch(`/api/model/ttl?building_id=${encodeURIComponent(buildingId)}`);
    ttl = typeof raw === "string" ? raw : raw?.ttl ?? JSON.stringify(raw, null, 2);
  } catch {
    ttl = "# TTL unavailable for this site (import or sync model first).\n";
  }

  const [agentCtx, mapping, historian] = await Promise.all([
    apiFetch(`/api/model/agent-context?building_id=${encodeURIComponent(buildingId)}`).catch(
      () => null,
    ),
    apiFetch(
      `/api/csv/import/package/mapping?building_id=${encodeURIComponent(buildingId)}`,
    ).catch(() => null),
    apiFetch(`/api/historian/points?building_id=${encodeURIComponent(buildingId)}`).catch(
      () => null,
    ),
  ]);

  const model = buildModel(buildingId, agentCtx, mapping, historian);
  return {
    buildingId,
    health,
    ttl,
    agentCtx,
    mapping,
    model,
    points: model.points,
    equips: model.equips,
  };
}

function buildModel(buildingId, agentCtx, mapping, historian) {
  const site = {
    id: buildingId,
    name: buildingId,
  };
  const equipById = new Map();
  const pointByKey = new Map();

  const tree = agentCtx?.model_tree;
  if (tree?.equipment && Array.isArray(tree.equipment)) {
    for (const row of tree.equipment) {
      const id = row.equipment_id || row.id;
      if (!id) continue;
      equipById.set(id, {
        id,
        name: row.display_name || id,
        equipType: stampFromTags(row.haystack_tags),
        tags: row.haystack_tags || [],
        siteRef: buildingId,
      });
    }
  }
  if (tree?.points && Array.isArray(tree.points)) {
    for (const row of tree.points) {
      const equipId = row.equipment_id || "";
      const role = row.role || row.column || row.point_id || "";
      const key = `${equipId}::${role}`;
      pointByKey.set(key, {
        id: key,
        siteRef: buildingId,
        equipRef: equipId,
        role,
        column: row.column || role,
        dis: row.point_id || row.column || role,
        tags: normalizeTags(row.haystack_tags, role),
        unit: row.unit || "",
        kind: isBoolRole({ role, tags: row.haystack_tags || [] }) ? "Bool" : "Number",
        latest: null,
      });
    }
  }

  const inv = mapping?.equipment;
  if (Array.isArray(inv)) {
    for (const eq of inv) {
      const id = eq.equipment_id;
      if (!id) continue;
      if (!equipById.has(id)) {
        equipById.set(id, {
          id,
          name: eq.display_name || id,
          equipType: eq.equipment_type || stampFromTags(eq.haystack_tags),
          tags: eq.haystack_tags || [],
          siteRef: buildingId,
        });
      }
      const cols = eq.columns || [];
      for (const col of cols) {
        const role = col.role || col.column;
        if (!role) continue;
        const key = `${id}::${role}`;
        if (pointByKey.has(key)) continue;
        pointByKey.set(key, {
          id: key,
          siteRef: buildingId,
          equipRef: id,
          role,
          column: col.column || role,
          dis: col.column || role,
          tags: normalizeTags(col.haystack_tags, role),
          unit: col.unit || "",
          kind: "Number",
          latest: null,
        });
      }
    }
  }

  const histPts = historian?.points;
  if (Array.isArray(histPts)) {
    for (const row of histPts) {
      const equipId = row.equipment_id || "";
      const role = row.role || "";
      if (!role) continue;
      const key = `${equipId}::${role}`;
      const existing = pointByKey.get(key);
      const tags = existing?.tags?.length
        ? existing.tags
        : normalizeTags([], role);
      pointByKey.set(key, {
        id: key,
        siteRef: buildingId,
        equipRef: equipId,
        role,
        column: existing?.column || role,
        dis: existing?.dis || role,
        tags,
        unit: row.unit || existing?.unit || "",
        kind: isBoolRole({ role, tags }) ? "Bool" : "Number",
        latest: null,
        openfddKey: row.openfdd_key,
      });
    }
  }

  return {
    site,
    equips: [...equipById.values()].sort((a, b) => a.id.localeCompare(b.id)),
    devices: [],
    points: [...pointByKey.values()].sort(
      (a, b) =>
        (a.equipRef || "").localeCompare(b.equipRef || "") ||
        displayName(a).localeCompare(displayName(b)),
    ),
  };
}

function stampFromTags(tags) {
  if (!Array.isArray(tags)) return "";
  for (const t of tags) {
    if (t === "ahu" || t === "vav" || t === "equip") return t;
  }
  return "";
}

function normalizeTags(rawTags, role) {
  const tags = Array.isArray(rawTags) ? [...rawTags] : [];
  if (!tags.includes("point")) tags.push("point");
  if (role.includes("web") || role === "web_oa_t") {
    if (!tags.includes("weather")) tags.push("weather");
  }
  if (role.endsWith("_status") || role.endsWith("_cmd")) {
    if (!tags.includes("sensor")) tags.push("sensor");
  }
  if (isTemp({ role, tags })) {
    for (const t of ["sensor", "temp"]) {
      if (!tags.includes(t)) tags.push(t);
    }
  }
  return tags;
}

export async function runSparql(buildingId, query) {
  return apiFetch("/api/model/sparql", {
    method: "POST",
    body: JSON.stringify({ building_id: buildingId, query }),
  });
}

export function esc(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/"/g, "&quot;");
}

export function applyLatestFromSeries(points, seriesRows, roleColumns) {
  if (!seriesRows?.length) return;
  const last = seriesRows[seriesRows.length - 1];
  const ts = last.timestamp_utc;
  for (const p of points) {
    const role = roleOf(p);
    if (!roleColumns.includes(role)) continue;
    const v = last[role];
    if (v == null) continue;
    p.latest = { ts, value: v };
  }
}

export function fmtPoint(p) {
  const v = p.latest?.value;
  if (v == null) return "–";
  if (p.kind === "Bool" || isBoolRole(p)) return v > 0.5 ? "on" : "off";
  const n = Number(v);
  if (!Number.isFinite(n)) return "–";
  return `${n.toFixed(2)} ${p.unit || ""}`.trim();
}

export {
  GENERIC,
  has,
  isBoolRole,
  isRH,
  isTemp,
  displayName,
  roleOf,
  tagsOf,
} from "./tags.js";
