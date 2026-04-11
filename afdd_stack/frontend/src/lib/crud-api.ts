import { apiFetch } from "@/lib/api";
import type {
  DataModelExportRow,
  DataModelImportBody,
  DataModelImportResponse,
  EnergyCalculation,
  EnergyCalculationCreateBody,
  EnergyCalculationPatchBody,
  EnergyCalculationsExportPayload,
  EnergyCalculationsImportBody,
  EnergyCalculationsImportResponse,
  EnergyCalcTypePublic,
  EnergyPreviewResult,
  PlatformConfig,
  Point,
  PointPatchBody,
  Site,
} from "@/types/api";

export interface SiteCreate {
  name: string;
  description?: string | null;
}

export interface DataModelCheckResponse {
  triple_count: number;
  blank_node_count: number;
  orphan_blank_nodes: number;
  sites: number;
  bacnet_devices: number;
  warnings: string[];
}

export function getConfig() {
  return apiFetch<PlatformConfig>("/config");
}

export function putConfig(body: PlatformConfig) {
  return apiFetch<PlatformConfig>("/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function createSite(body: SiteCreate) {
  return apiFetch<Site>("/sites", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteSite(siteId: string) {
  return apiFetch<{ status: string }>(`/sites/${siteId}`, {
    method: "DELETE",
  });
}

export function deleteEquipment(equipmentId: string) {
  return apiFetch<{ status: string }>(`/equipment/${equipmentId}`, {
    method: "DELETE",
  });
}

export function deletePoint(pointId: string) {
  return apiFetch<{ status: string }>(`/points/${pointId}`, {
    method: "DELETE",
  });
}

export type PointCreateBody = {
  site_id: string;
  external_id: string;
  brick_type?: string | null;
  fdd_input?: string | null;
  unit?: string | null;
  description?: string | null;
  equipment_id?: string | null;
  bacnet_device_id?: string | null;
  object_identifier?: string | null;
  object_name?: string | null;
  polling?: boolean | null;
};

export function createPoint(body: PointCreateBody): Promise<Point> {
  return apiFetch<Point>("/points", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** PATCH a point — any subset of PointPatchBody (matches backend PointUpdate). */
export function updatePoint(pointId: string, body: PointPatchBody): Promise<Point> {
  return apiFetch<Point>(`/points/${pointId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function dataModelExport() {
  return apiFetch<DataModelExportRow[]>("/data-model/export");
}

export function dataModelImport(body: DataModelImportBody) {
  return apiFetch<DataModelImportResponse>("/data-model/import", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function dataModelSerialize() {
  return apiFetch<{ status: string; path?: string; path_resolved?: string; error?: string }>(
    "/data-model/serialize",
    { method: "POST" },
  );
}

export function dataModelReset() {
  return apiFetch<{ status: string; path?: string; message?: string; error?: string }>(
    "/data-model/reset",
    { method: "POST" },
  );
}

export function dataModelCheck() {
  return apiFetch<DataModelCheckResponse>("/data-model/check");
}

export function listEnergyCalcTypes() {
  return apiFetch<{ calc_types: EnergyCalcTypePublic[] }>("/energy-calculations/calc-types");
}

export function listEnergyCalculations(siteId: string, equipmentId?: string) {
  const p = new URLSearchParams();
  p.set("site_id", siteId);
  if (equipmentId) p.set("equipment_id", equipmentId);
  return apiFetch<EnergyCalculation[]>(`/energy-calculations?${p.toString()}`);
}

export function previewEnergyCalculation(
  calc_type: string,
  parameters: Record<string, unknown>,
) {
  return apiFetch<EnergyPreviewResult>("/energy-calculations/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ calc_type, parameters }),
  });
}

export function createEnergyCalculation(body: EnergyCalculationCreateBody) {
  return apiFetch<EnergyCalculation>("/energy-calculations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteEnergyCalculation(id: string) {
  return apiFetch<{ status: string }>(`/energy-calculations/${id}`, {
    method: "DELETE",
  });
}

export function exportEnergyCalculations(siteId: string) {
  const q = new URLSearchParams();
  q.set("site_id", siteId);
  return apiFetch<EnergyCalculationsExportPayload>(`/energy-calculations/export?${q.toString()}`);
}

export function importEnergyCalculations(body: EnergyCalculationsImportBody) {
  return apiFetch<EnergyCalculationsImportResponse>("/energy-calculations/import", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function seedDefaultPenaltyCatalog(siteId: string, replace = false) {
  const q = new URLSearchParams();
  q.set("site_id", siteId);
  if (replace) q.set("replace", "true");
  return apiFetch<{
    site_id: string;
    created: number;
    rows_in_catalog: number;
    deleted_before_insert: number;
    replace: boolean;
  }>(`/energy-calculations/seed-default-penalty-catalog?${q.toString()}`, { method: "POST" });
}

export function updateEnergyCalculation(id: string, patch: EnergyCalculationPatchBody) {
  return apiFetch<EnergyCalculation>(`/energy-calculations/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

// Rules API (FDD rule YAML: list, upload, delete, sync definitions)
export function uploadRule(filename: string, content: string) {
  return apiFetch<{ ok: boolean; path?: string; filename?: string }>("/rules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename, content }),
  });
}

export function deleteRule(filename: string) {
  return apiFetch<{ ok?: boolean; filename?: string }>(`/rules/${encodeURIComponent(filename)}`, {
    method: "DELETE",
  });
}

export function syncRuleDefinitions() {
  return apiFetch<{ ok: boolean }>("/rules/sync-definitions", {
    method: "POST",
  });
}
