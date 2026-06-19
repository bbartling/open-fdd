/** Niagara baskStream REST helpers (browser → Open-FDD bridge only). */

import { apiFetch } from "./api";
import type { NiagaraCommissionProfile } from "./niagaraCommissionProfile";

export type NiagaraStation = {
  id: string;
  name: string;
  station_url: string;
  username: string;
  password_env: string;
  password?: string;
  password_configured?: boolean;
  verify_tls: boolean;
  enabled: boolean;
  root_ord: string;
  poll_interval_seconds: number;
  read_batch_size: number;
  browse_depth: number;
  max_nodes: number;
  include_patterns: string[];
  exclude_patterns: string[];
  default_points_root: string;
  follow_external: boolean;
  include_proxy_ext: boolean;
  commission_profile?: NiagaraCommissionProfile;
};

export type NiagaraPoint = {
  point_id?: string;
  station_id: string;
  station_name?: string;
  device_ord?: string;
  device_name?: string;
  point_ord: string;
  point_name: string;
  display_name?: string;
  type_spec?: string;
  value_type?: string;
  kind?: string;
  writable?: boolean;
  status?: string;
  ok?: boolean;
  facets?: unknown;
  units?: string;
  source?: string;
  driver_path?: string;
  discovered_at?: string;
  value?: unknown;
  display_value?: unknown;
  timestamp?: string;
};

export type NiagaraDevice = {
  station_id: string;
  station_name: string;
  station_url: string;
  point_count: number;
  poll_running?: boolean;
  points: NiagaraPoint[];
};

export type NiagaraPollStatus = {
  station_id: string;
  running: boolean;
  connected: boolean;
  last_success?: string;
  last_error?: string;
  active_points: number;
  last_poll_duration_ms: number;
  batch_count: number;
};

export type NiagaraTreeNode = {
  indent: number;
  name: string;
  ord: string;
  type: string;
  status: string;
};

export type NiagaraSchedule = {
  name: string;
  ord: string;
  type: string;
  status: string;
  schedule?: unknown;
  schedule_error?: string;
};

export async function fetchNiagaraHealth() {
  return apiFetch<{
    ok: boolean;
    connector: string;
    read_only: boolean;
    dependencies_ok: boolean;
    dependencies_error?: string;
    station_count: number;
  }>("/api/niagara/health");
}

export async function fetchNiagaraStations() {
  return apiFetch<{ stations: NiagaraStation[]; count: number }>("/api/niagara/stations");
}

export async function saveNiagaraStation(station: Partial<NiagaraStation> & { name: string; station_url: string; username: string }) {
  const method = station.id ? "PUT" : "POST";
  const path = station.id ? `/api/niagara/stations/${encodeURIComponent(station.id)}` : "/api/niagara/stations";
  return apiFetch<{ ok: boolean; station: NiagaraStation }>(path, {
    method,
    body: JSON.stringify(station),
  });
}

export async function deleteNiagaraStation(stationId: string) {
  return apiFetch<{ ok: boolean; station_id: string }>(`/api/niagara/stations/${encodeURIComponent(stationId)}`, {
    method: "DELETE",
  });
}

export async function testNiagaraStation(stationId: string) {
  return apiFetch<{ ok: boolean; authenticated_user?: string; capabilities?: unknown }>(
    `/api/niagara/stations/${encodeURIComponent(stationId)}/test`,
    { method: "POST" },
  );
}

export async function testNiagaraDraft(body: {
  station_url: string;
  username: string;
  password: string;
  verify_tls?: boolean;
}) {
  return apiFetch<{ ok: boolean; authenticated_user?: string; capabilities?: unknown }>(
    "/api/niagara/stations/test-draft",
    { method: "POST", body: JSON.stringify(body) },
  );
}

export async function discoverNiagaraPoints(
  stationId: string,
  body?: { base?: string; depth?: number; query?: string; follow_external?: boolean; include_proxy_ext?: boolean },
) {
  return apiFetch<{ station_id: string; base: string; count: number; points: NiagaraPoint[] }>(
    `/api/niagara/stations/${encodeURIComponent(stationId)}/discover`,
    { method: "POST", body: JSON.stringify(body ?? {}) },
  );
}

export async function discoverNiagaraProfile(
  stationId: string,
  body?: { device_ids?: string[]; follow_external?: boolean; include_proxy_ext?: boolean },
) {
  return apiFetch<{
    station_id: string;
    count: number;
    devices_scanned: number;
    devices: { device_id?: string; label?: string; folder_ord?: string; points_root?: string; count?: number }[];
    points: NiagaraPoint[];
  }>(`/api/niagara/stations/${encodeURIComponent(stationId)}/discover-profile`, {
    method: "POST",
    body: JSON.stringify(body ?? {}),
  });
}

export async function fetchNiagaraTree(stationId: string, base: string, depth = 3, followExternal?: boolean) {
  const params = new URLSearchParams({ base, depth: String(depth) });
  if (followExternal != null) params.set("follow_external", String(followExternal));
  return apiFetch<{ base: string; depth: number; nodes: NiagaraTreeNode[]; count: number }>(
    `/api/niagara/stations/${encodeURIComponent(stationId)}/tree?${params}`,
  );
}

export async function readNiagaraPoints(stationId: string, ords: string[], store = false) {
  return apiFetch<{ station_id: string; count: number; values: NiagaraPoint[] }>(
    `/api/niagara/stations/${encodeURIComponent(stationId)}/read`,
    { method: "POST", body: JSON.stringify({ ords, store }) },
  );
}

export async function fetchNiagaraDriverTree() {
  return apiFetch<{ devices: NiagaraDevice[]; source: string }>("/api/niagara/driver/tree");
}

export async function fetchNiagaraPollStatus(stationId: string) {
  return apiFetch<NiagaraPollStatus>(`/api/niagara/stations/${encodeURIComponent(stationId)}/poll/status`);
}

export async function startNiagaraPoll(stationId: string) {
  return apiFetch<NiagaraPollStatus>(`/api/niagara/stations/${encodeURIComponent(stationId)}/poll/start`, {
    method: "POST",
  });
}

export async function stopNiagaraPoll(stationId: string) {
  return apiFetch<NiagaraPollStatus>(`/api/niagara/stations/${encodeURIComponent(stationId)}/poll/stop`, {
    method: "POST",
  });
}

export async function pollNiagaraOnce(stationId: string) {
  return apiFetch<{ station_id: string; samples: number; batches?: number; duration_ms?: number }>(
    `/api/niagara/stations/${encodeURIComponent(stationId)}/poll/once`,
    { method: "POST" },
  );
}

export async function fetchNiagaraSchedules(stationId: string, base?: string, read = false) {
  const params = new URLSearchParams();
  if (base) params.set("base", base);
  if (read) params.set("read", "true");
  const qs = params.toString();
  return apiFetch<{ station_id: string; base: string; count: number; schedules: NiagaraSchedule[] }>(
    `/api/niagara/stations/${encodeURIComponent(stationId)}/schedules${qs ? `?${qs}` : ""}`,
  );
}

/** Preserve Niagara ORD encoding — never decode $20/$2d in UI helpers. */
export function preserveNiagaraOrd(ord: string): string {
  return String(ord ?? "");
}

export function exportPointsCsv(points: NiagaraPoint[]): string {
  const header = ["point_name", "point_ord", "value", "status", "units", "type_spec"];
  const rows = points.map((p) =>
    [
      p.point_name,
      preserveNiagaraOrd(p.point_ord),
      p.display_value ?? p.value ?? "",
      p.status ?? "",
      p.units ?? "",
      p.type_spec ?? "",
    ]
      .map((v) => `"${String(v).replace(/"/g, '""')}"`)
      .join(","),
  );
  return [header.join(","), ...rows].join("\n");
}

export function exportPointsJson(points: NiagaraPoint[]): string {
  return JSON.stringify(
    points.map((p) => ({ ...p, point_ord: preserveNiagaraOrd(p.point_ord) })),
    null,
    2,
  );
}
