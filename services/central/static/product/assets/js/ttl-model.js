/** Model tree from SPARQL-backed server projection (GET /api/model/projection). */

function uiModelFromProjection(buildingId, payload) {
  if (!payload || payload.ok === false) {
    return {
      site: { id: buildingId, name: buildingId },
      equips: [],
      devices: [],
      points: [],
    };
  }
  const site = payload.site || { id: buildingId, name: buildingId };
  const equips = Array.isArray(payload.equips) ? payload.equips : [];
  const points = (Array.isArray(payload.points) ? payload.points : []).map((p) => ({
    ...p,
    latest: p.latest ?? null,
    unit: p.unit ?? "",
    kind: p.kind ?? null,
  }));
  return { site, equips, devices: payload.devices || [], points };
}

export async function loadModelFromTtl(buildingId, apiFetch) {
  let ttl = "";
  try {
    const raw = await apiFetch(`/api/model/ttl?building_id=${encodeURIComponent(buildingId)}`);
    ttl = typeof raw === "string" ? raw : raw?.ttl ?? "";
  } catch {
    ttl = "# TTL unavailable for this site.\n";
  }
  let model = uiModelFromProjection(buildingId, null);
  try {
    const projection = await apiFetch(
      `/api/model/projection?building_id=${encodeURIComponent(buildingId)}`,
    );
    model = uiModelFromProjection(buildingId, projection);
  } catch {
    model = uiModelFromProjection(buildingId, null);
  }
  return { ttl, model };
}

export async function loadModelProjection(buildingId, apiFetch) {
  const projection = await apiFetch(
    `/api/model/projection?building_id=${encodeURIComponent(buildingId)}`,
  );
  return uiModelFromProjection(buildingId, projection);
}
