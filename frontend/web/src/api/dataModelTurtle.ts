import type { PackageMappingResponse } from "./mappingApi";

/** Escape a Turtle string literal (quoted). */
export function turtleEscape(s: string): string {
  return s
    .replace(/\\/g, "\\\\")
    .replace(/"/g, '\\"')
    .replace(/\n/g, "\\n")
    .replace(/\r/g, "\\r");
}

/** Lowercase hex of UTF-8 bytes — shared with Rust `iri_segment`. */
function utf8Hex(s: string): string {
  const bytes = new TextEncoder().encode(s);
  let out = "";
  for (let i = 0; i < bytes.length; i++) {
    out += bytes[i]!.toString(16).padStart(2, "0");
  }
  return out;
}

/**
 * Stable ofdd IRI local-name segment (openfdd_data_model_v2).
 * Safe ASCII ids (`[A-Za-z0-9._-]`) that do **not** start with reserved
 * prefix `enc_` and do not contain `__` pass through; otherwise reversible
 * `enc_<utf8-hex>`. Reserving `enc_` keeps `AHU 1` and literal id
 * `enc_4148552031` distinct (DM-01).
 */
export function turtleIriSegment(s: string): string {
  const safe =
    /^[A-Za-z0-9._-]+$/.test(s) &&
    !s.startsWith("enc_") &&
    !s.includes("__");
  if (safe) return s;
  return `enc_${utf8Hex(s)}`;
}

/** Building subject local name (v2 unambiguous). */
export function turtleBuildingSubject(buildingId: string): string {
  return `ofdd:b_${turtleIriSegment(buildingId)}`;
}

/** Equipment subject — tuple uses `__` so building/equip labels cannot collide (DM-02). */
export function turtleEquipmentSubject(
  buildingId: string,
  equipmentId: string,
): string {
  return `ofdd:eq_${turtleIriSegment(buildingId)}__${turtleIriSegment(equipmentId)}`;
}

/**
 * Project package mapping inventory to Turtle (`openfdd_data_model_v2` export).
 * Never invents cookbook roles — only emits roles present on equipment.
 */
export function buildDataModelTurtle(inventory: PackageMappingResponse): string {
  const buildingId = (inventory.building_id ?? "unknown").trim() || "unknown";
  const bSubj = turtleBuildingSubject(buildingId);
  const lines: string[] = [
    "@prefix ofdd: <urn:openfdd:ns#> .",
    "@prefix hs: <https://project-haystack.org/def/ph#> .",
    "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
    "",
    `${bSubj} a ofdd:Building ;`,
    `  ofdd:buildingId "${turtleEscape(buildingId)}" .`,
    "",
  ];

  for (const eq of inventory.equipment ?? []) {
    const eidRaw = (eq.equipment_id ?? "").trim();
    if (!eidRaw) continue;
    const subj = turtleEquipmentSubject(buildingId, eidRaw);
    lines.push(`${subj} a ofdd:Equipment ;`);
    lines.push(`  ofdd:equipmentId "${turtleEscape(eidRaw)}" ;`);
    lines.push(
      `  ofdd:equipmentType "${turtleEscape(eq.equipment_type || "unknown")}" ;`,
    );
    lines.push(`  ofdd:inBuilding ${bSubj} ;`);
    const parent = eq.parent_ahu?.trim();
    const parentSource = (eq.parent_ahu_source ?? "package").trim();
    // DM-04: guessed parents stay out of Turtle fact edges.
    if (parent && parentSource !== "inferred") {
      lines.push(
        `  ofdd:parentAhu ${turtleEquipmentSubject(buildingId, parent)} ;`,
      );
    }

    const roles = eq.roles ?? {};
    const roleEntries = Object.entries(roles).filter(
      ([, role]) => typeof role === "string" && role.trim().length > 0,
    );

    if (roleEntries.length === 0) {
      const last = lines.pop()!;
      lines.push(last.replace(/\s*;\s*$/, " ."));
      lines.push("");
      // DM-03: still emit unmapped columns for empty-role equipment.
      for (const col of eq.unmapped_columns ?? []) {
        if (!col?.trim()) continue;
        lines.push(
          `${subj} ofdd:unmappedColumn "${turtleEscape(col.trim())}" .`,
        );
      }
      if ((eq.unmapped_columns ?? []).some((c) => c?.trim())) {
        lines.push("");
      }
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
