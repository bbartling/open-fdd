import { apiFetch } from "./api.js";
import { loadModelFromTtl } from "./ttl-model.js";
import { displayName, isBoolRole, isTemp, roleOf } from "./tags.js";

/** Model tab: TTL + SPARQL only (no agent-context or package mapping). */

export async function loadBuildingContext(buildingId) {
  const health = await apiFetch("/api/health");
  const { ttl, model } = await loadModelFromTtl(buildingId, apiFetch);
  return {
    buildingId,
    health,
    ttl,
    model,
    points: model.points,
    equips: model.equips,
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
