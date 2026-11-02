import type { MappingEquipment, PackageMappingResponse } from "../api/mappingApi";

/** Every edited column, including an intentional empty role. */
export function seedDraftRoles(eq: MappingEquipment | null): Record<string, string> {
  const draft: Record<string, string> = {};
  for (const col of eq?.columns ?? []) {
    const column = col.column;
    if (!column || column in draft) continue;
    draft[column] = (col.role ?? "").trim();
  }
  for (const [column, role] of Object.entries(eq?.roles ?? {})) {
    if (!column || column in draft) continue;
    draft[column] = role.trim();
  }
  for (const column of eq?.unmapped_columns ?? []) {
    if (!column || column in draft) continue;
    draft[column] = "";
  }
  return draft;
}

export function columnNames(eq: MappingEquipment | null): string[] {
  return Object.keys(seedDraftRoles(eq));
}

/** Empty string is a draft clear. The saved role is not put back. */
export function setDraftRole(
  draft: Record<string, string>,
  column: string,
  role: string,
): Record<string, string> {
  return { ...draft, [column]: role.trim() };
}

/** Persist only non-empty roles. A missing key is the cleared role. */
export function rolesForSave(draft: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [column, role] of Object.entries(draft)) {
    const trimmed = role.trim();
    if (trimmed) out[column] = trimmed;
  }
  return out;
}

export interface RevisionLabels {
  draft: string;
  saved: string;
  active: string;
}

export function mappingRevisionLabels(input: {
  dirty: boolean;
  draftRoles: Record<string, string>;
  savedRoles: Record<string, string>;
  savedAuthorityLabel: string | null;
  activeIngestRevision: string | null;
}): RevisionLabels {
  const columns = new Set([
    ...Object.keys(input.draftRoles),
    ...Object.keys(input.savedRoles),
  ]);
  const cleared = [...columns]
    .filter((column) => {
      const saved = (input.savedRoles[column] ?? "").trim();
      const draft = (input.draftRoles[column] ?? "").trim();
      return saved.length > 0 && draft.length === 0;
    })
    .sort((a, b) => a.localeCompare(b));
  const changed = [...columns].some(
    (column) =>
      (input.draftRoles[column] ?? "").trim() !== (input.savedRoles[column] ?? "").trim(),
  );

  let draft: string;
  if (!input.dirty && !changed) {
    draft = "Draft: matches saved";
  } else if (cleared.length > 0) {
    draft = `Draft: ${cleared.map((column) => `${column} unmapped`).join(", ")}`;
  } else {
    draft = "Draft: unsaved role edits";
  }

  const authority =
    (input.savedAuthorityLabel ?? "").trim() || "Saved column map";
  const savedPairs = Object.entries(input.savedRoles)
    .filter(([, role]) => role.trim().length > 0)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([column, role]) => `${column} → ${role.trim()}`);
  const saved = savedPairs.length
    ? `${authority}: ${savedPairs.join(", ")}`
    : `${authority}: no roles`;

  const revision = (input.activeIngestRevision ?? "").trim();
  const active = revision
    ? `Active ingest: ${revision}`
    : "Active ingest: not reported";
  return { draft, saved, active };
}

export function savedAuthorityLabel(inventory: PackageMappingResponse | null): string {
  const fromServer = inventory?.revisions?.saved?.label?.trim();
  if (fromServer) return fromServer;
  if (inventory?.source === "timescale_sample") return "Saved sample role keys";
  return "Saved column map";
}

export function activeIngestRevision(inventory: PackageMappingResponse | null): string | null {
  const revision = inventory?.revisions?.active_ingest?.revision_id;
  if (typeof revision !== "string") return null;
  const trimmed = revision.trim();
  return trimmed.length > 0 ? trimmed : null;
}
