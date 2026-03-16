import { apiFetch } from "@/lib/api";
import type {
  AiAgentRequest,
  AiAgentResponse,
  DataModelExportRow,
  DataModelImportBody,
  DataModelImportResponse,
  PlatformConfig,
  Point,
  Site,
  TagWithOpenAiRequest,
  TagWithOpenAiResponse,
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

export interface WhoIsRangeBody {
  request: {
    start_instance: number;
    end_instance: number;
  };
  url?: string;
}

export interface PointDiscoveryBody {
  instance: {
    device_instance: number;
  };
  url?: string;
}

export interface PointDiscoveryToGraphBody extends PointDiscoveryBody {
  update_graph?: boolean;
  write_file?: boolean;
}

export interface WhoIsResponse {
  ok?: boolean;
  body?: unknown;
  error?: string;
}

export interface PointDiscoveryResponse {
  ok?: boolean;
  body?: unknown;
  error?: string;
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

/** PATCH a point (e.g. set polling so BACnet scraper includes it). */
export function updatePoint(
  pointId: string,
  body: { polling?: boolean },
): Promise<Point> {
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

export function tagPointsWithOpenAi(body: TagWithOpenAiRequest) {
  return apiFetch<TagWithOpenAiResponse>("/data-model/tag-with-openai", {
    method: "POST",
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

export function bacnetWhoisRange(body: WhoIsRangeBody) {
  return apiFetch<WhoIsResponse>("/bacnet/whois_range", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function bacnetPointDiscovery(body: PointDiscoveryBody) {
  return apiFetch<PointDiscoveryResponse>("/bacnet/point_discovery", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function bacnetPointDiscoveryToGraph(body: PointDiscoveryToGraphBody) {
  return apiFetch<PointDiscoveryResponse>("/bacnet/point_discovery_to_graph", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
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

export function callAiAgent(body: AiAgentRequest) {
  return apiFetch<AiAgentResponse>("/ai/agent", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}