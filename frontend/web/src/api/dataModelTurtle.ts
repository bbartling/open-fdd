import type { PackageMappingResponse } from "./mappingApi";

/** Escape a Turtle string literal (quoted). */
export function turtleEscape(s: string): string {
  return s
    .replace(/\\/g, "\\\\")
    .replace(/"/g, '\\"')
    .replace(/\n/g, "\\n")
    .replace(/\r/g, "\\r");
}

/** Stable FNV-1a 32-bit for collision-free IRI segments. */
function fnv1a32(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/**
 * Sanitize path segments for stable ofdd IRIs.
 * When sanitization would collide distinct IDs (`AHU 1` vs `AHU_1`), append a
 * deterministic hash of the raw id so RDF subjects stay unique.
 */
export function turtleIriSegment(s: string): string {
  const sanitized = s.replace(/[^A-Za-z0-9._-]+/g, "_");
  if (sanitized === s) return sanitized;
  const base = sanitized.replace(/^_+|_+$/g, "") || "x";
  return `${base}_${fnv1a32(s).toString(16)}`;
}

/**
 * Project package mapping inventory to Turtle (`openfdd_data_model_v1` export).
 * Never invents cookbook roles — only emits roles present on equipment.
 */
export function buildDataModelTurtle(inventory: PackageMappingResponse): string {
  const buildingId = (inventory.building_id ?? "unknown").trim() || "unknown";
  const bid = turtleIriSegment(buildingId);
  const lines: string[] = [
    "@prefix ofdd: <urn:openfdd:ns#> .",
    "@prefix hs: <https://project-haystack.org/def/ph#> .",
    "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
    "",
    `ofdd:building_${bid} a ofdd:Building ;`,
    `  ofdd:buildingId "${turtleEscape(buildingId)}" .`,
    "",
  ];

  for (const eq of inventory.equipment ?? []) {
    const eidRaw = (eq.equipment_id ?? "").trim();
    if (!eidRaw) continue;
    const eid = turtleIriSegment(eidRaw);
    const subj = `ofdd:building_${bid}_equip_${eid}`;
    lines.push(`${subj} a ofdd:Equipment ;`);
    lines.push(`  ofdd:equipmentId "${turtleEscape(eidRaw)}" ;`);
    lines.push(
      `  ofdd:equipmentType "${turtleEscape(eq.equipment_type || "unknown")}" ;`,
    );
    lines.push(`  ofdd:inBuilding ofdd:building_${bid} ;`);
    const parent = eq.parent_ahu?.trim();
    if (parent) {
      lines.push(
        `  ofdd:parentAhu ofdd:building_${bid}_equip_${turtleIriSegment(parent)} ;`,
      );
    }

    const roles = eq.roles ?? {};
    const roleEntries = Object.entries(roles).filter(
      ([, role]) => typeof role === "string" && role.trim().length > 0,
    );
    if (roleEntries.length === 0) {
      // Drop trailing `;` before `.` on last property — rewrite last line.
      const last = lines.pop()!;
      lines.push(last.replace(/\s*;\s*$/, " ."));
      lines.push("");
      continue;
    }

    for (let i = 0; i < roleEntries.length; i++) {
      const [column, role] = roleEntries[i]!;
      const isLast = i === roleEntries.length - 1;
      const term = isLast ? " ." : " ;";
      lines.push(
        `  ofdd:roleBinding [ ofdd:role "${turtleEscape(role.trim())}" ; ofdd:column "${turtleEscape(column)}" ]${term}`,
      );
    }
    lines.push("");

    for (const col of eq.unmapped_columns ?? []) {
      if (!col?.trim()) continue;
      lines.push(
        `${subj} ofdd:unmappedColumn "${turtleEscape(col.trim())}" .`,
      );
    }
    if ((eq.unmapped_columns ?? []).some((c) => c?.trim())) {
      lines.push("");
    }
  }

  return lines.join("\n").replace(/\n{3,}/g, "\n\n");
}
