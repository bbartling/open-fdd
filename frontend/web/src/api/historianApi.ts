import { apiFetch } from "./client";

/** One historian series (`point_map` row) for a site. */
export interface HistorianPoint {
  equipment_id: string | null;
  equip_type: string | null;
  openfdd_key: string;
  role: string | null;
  unit: string | null;
  portal_point_id: string | null;
  /** False when the latest model no longer references this point. */
  referenced: boolean;
}

export interface HistorianPointsResponse {
  ok: boolean;
  building_id: string;
  historian?: string;
  points: HistorianPoint[];
  error?: string;
}

export interface HistorianOrphansResponse {
  ok: boolean;
  building_id: string;
  historian?: string;
  orphaned_points: number;
  equipment: string[];
  points: HistorianPoint[];
  error?: string;
}

export interface PurgeReport {
  keys: string[];
  samples_deleted: number;
  point_map_deleted: number;
  role_map_deleted: number;
}

export interface HistorianPurgeResponse {
  ok: boolean;
  building_id: string;
  equipment_id?: string | null;
  openfdd_key?: string | null;
  purge?: PurgeReport;
  error?: string;
}

export type PurgeTarget =
  | { kind: "equipment"; equipmentId: string }
  | { kind: "point"; openfddKey: string };

export function historianPointsPath(buildingId: string): string {
  return `/api/historian/points?building_id=${encodeURIComponent(buildingId)}`;
}

export function historianOrphansPath(buildingId: string): string {
  return `/api/historian/orphans?building_id=${encodeURIComponent(buildingId)}`;
}

export async function getHistorianPoints(
  buildingId: string,
  signal?: AbortSignal,
): Promise<HistorianPointsResponse> {
  return apiFetch<HistorianPointsResponse>(historianPointsPath(buildingId), { signal });
}

export async function getHistorianOrphans(
  buildingId: string,
  signal?: AbortSignal,
): Promise<HistorianOrphansResponse> {
  return apiFetch<HistorianOrphansResponse>(historianOrphansPath(buildingId), { signal });
}

/** Deletes samples and `point_map` rows only. The building model is untouched. */
export async function purgeHistorian(
  buildingId: string,
  target: PurgeTarget,
): Promise<HistorianPurgeResponse> {
  const body =
    target.kind === "equipment"
      ? { building_id: buildingId, equipment_id: target.equipmentId, confirm: true }
      : { building_id: buildingId, openfdd_key: target.openfddKey, confirm: true };
  const out = await apiFetch<HistorianPurgeResponse>("/api/historian/purge", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!out.ok) {
    throw new Error(out.error || "Historian purge failed");
  }
  return out;
}
