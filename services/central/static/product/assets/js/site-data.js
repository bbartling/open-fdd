import { apiFetch } from "./api.js";
import { isBoolRole, normalizeTags, roleOf } from "./tags.js";
import { confirmMinForRule as confirmMinForRuleImpl } from "./rule-params.js";
import { loadModelProjection } from "./ttl-model.js";

/** Historian + package mapping for Charts / Points / FDD / RCx (not Model tab). */

export async function loadSiteData(buildingId) {
  const [mapping, historian, sessionConfig, graphModel] = await Promise.all([
    apiFetch(
      `/api/csv/import/package/mapping?building_id=${encodeURIComponent(buildingId)}`,
    ).catch(() => null),
    apiFetch(`/api/historian/points?building_id=${encodeURIComponent(buildingId)}`).catch(
      () => null,
    ),
    apiFetch(`/api/fdd/session-config?building_id=${encodeURIComponent(buildingId)}`).catch(
      () => null,
    ),
    loadModelProjection(buildingId, apiFetch).catch(() => null),
  ]);
  const model = buildOperationalModel(buildingId, mapping, historian, graphModel);
  return { mapping, historian, sessionConfig, model, graphModel };
}

function historianIndex(historian) {
  const byKey = new Map();
  const histPts = historian?.points;
  if (!Array.isArray(histPts)) return byKey;
  for (const row of histPts) {
    const equipId = row.equipment_id || "";
    const role = row.role || "";
    if (row.openfdd_key) {
      byKey.set(String(row.openfdd_key), row);
    }
    if (equipId && role) {
      byKey.set(`${equipId}::${role}`, row);
    }
    if (equipId && row.point_id) {
      byKey.set(`${equipId}::${row.point_id}`, row);
    }
  }
  return byKey;
}

function mergeHistorianRow(point, histByKey) {
  const equipId = point.equipRef || "";
  const role = point.role || "";
  const candidates = [
    point.openfddKey,
    point.subjectIri,
    point.id,
    point.pointId,
    equipId && role ? `${equipId}::${role}` : "",
    equipId && point.pointId ? `${equipId}::${point.pointId}` : "",
  ].filter(Boolean);
  for (const key of candidates) {
    const row = histByKey.get(String(key));
    if (row) return row;
  }
  return null;
}

function buildOperationalModel(buildingId, mapping, historian, graphModel) {
  const histByKey = historianIndex(historian);
  if (graphModel?.points?.length) {
    const equipById = new Map();
    for (const eq of graphModel.equips || []) {
      if (eq?.id) equipById.set(eq.id, eq);
    }
    const points = graphModel.points.map((p) => {
      const hist = mergeHistorianRow(p, histByKey);
      const tags = Array.isArray(p.tags) ? p.tags : normalizeTags([], p.role || "");
      const kind =
        p.kind === "Bool" || p.kind === "Number"
          ? p.kind
          : hist && isBoolRole({ role: p.role, kind: "Bool", tags: [] })
            ? "Bool"
            : p.kind || null;
      return {
        ...p,
        siteRef: p.siteRef || buildingId,
        tags,
        unit: p.unit || hist?.unit || "",
        kind,
        openfddKey: hist?.openfdd_key,
        latest: null,
      };
    });
    return {
      site: graphModel.site || { id: buildingId, name: buildingId },
      equips: [...(graphModel.equips || [])].sort((a, b) => a.id.localeCompare(b.id)),
      devices: graphModel.devices || [],
      points,
    };
  }

  const equipById = new Map();
  const pointByKey = new Map();
  const inv = mapping?.equipment;
  if (Array.isArray(inv)) {
    for (const eq of inv) {
      const id = eq.equipment_id;
      if (!id) continue;
      equipById.set(id, {
        id,
        name: eq.display_name || id,
        equipType: eq.equipment_type || "",
        tags: eq.haystack_tags || [],
        siteRef: buildingId,
        sampling: eq.sampling,
      });
      for (const col of eq.columns || []) {
        const role = col.role || col.column;
        if (!role) continue;
        const key = `${id}::${role}`;
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
      const opaque = row.openfdd_key || `${equipId}::${role}`;
      const existing = pointByKey.get(`${equipId}::${role}`);
      pointByKey.set(opaque, {
        id: opaque,
        siteRef: buildingId,
        equipRef: equipId,
        role,
        column: existing?.column || role,
        dis: existing?.dis || role,
        tags: existing?.tags?.length ? existing.tags : normalizeTags([], role),
        unit: row.unit || existing?.unit || "",
        kind:
          row.kind === "Bool" || row.kind === "Number"
            ? row.kind
            : isBoolRole({ role, kind: row.kind, tags: [] })
              ? "Bool"
              : "Number",
        latest: null,
        openfddKey: row.openfdd_key,
      });
    }
  }
  return {
    site: { id: buildingId, name: buildingId },
    equips: [...equipById.values()].sort((a, b) => a.id.localeCompare(b.id)),
    devices: [],
    points: [...pointByKey.values()],
  };
}

export function confirmMinForRule(sessionConfig, ruleId, ruleMeta) {
  return confirmMinForRuleImpl(sessionConfig, ruleId, ruleMeta);
}

export { roleOf };
