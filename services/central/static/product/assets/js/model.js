import { apiFetch } from "./api.js";

/** Open-FDD model adapter (replaces NF Haystack model.js). Wave C fills inventory/SPARQL. */
export async function loadBuildingContext(buildingId) {
  const health = await apiFetch("/api/health");
  let ttl = "";
  try {
    const raw = await apiFetch(`/api/model/ttl?building_id=${encodeURIComponent(buildingId)}`);
    ttl = typeof raw === "string" ? raw : raw?.ttl ?? JSON.stringify(raw, null, 2);
  } catch {
    ttl = "# TTL unavailable for this site (import or sync model first).\n";
  }
  return {
    buildingId,
    health,
    ttl,
    points: [],
    equips: [],
  };
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
