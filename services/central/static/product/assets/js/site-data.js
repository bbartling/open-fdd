import { apiFetch } from "./api.js";
import { isBoolRole, normalizeTags, roleOf } from "./tags.js";
import { confirmMinForRule as confirmMinForRuleImpl } from "./rule-params.js";

/** Historian + package mapping for Charts / Points / FDD / RCx (not Model tab). */

export async function loadSiteData(buildingId) {
  const [mapping, historian, sessionConfig] = await Promise.all([
    apiFetch(
      `/api/csv/import/package/mapping?building_id=${encodeURIComponent(buildingId)}`,
    ).catch(() => null),
    apiFetch(`/api/historian/points?building_id=${encodeURIComponent(buildingId)}`).catch(
      () => null,
    ),
    apiFetch(`/api/fdd/session-config?building_id=${encodeURIComponent(buildingId)}`).catch(
      () => null,
    ),
  ]);
  const model = buildOperationalModel(buildingId, mapping, historian);
  return { mapping, historian, sessionConfig, model };
}

function buildOperationalModel(buildingId, mapping, historian) {
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
      const key = `${equipId}::${role}`;
      const existing = pointByKey.get(key);
      pointByKey.set(key, {
        id: key,
        siteRef: buildingId,
        equipRef: equipId,
        role,
        column: existing?.column || role,
        dis: existing?.dis || role,
        tags: existing?.tags?.length ? existing.tags : normalizeTags([], role),
        unit: row.unit || existing?.unit || "",
        kind: isBoolRole({ role, tags: [] }) ? "Bool" : "Number",
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
