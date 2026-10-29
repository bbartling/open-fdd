import type { OptionalFetch } from "../api/providersApi";

export interface IngestCatchupDevice {
  device_id?: string;
  mode?: string;
  last_stored_ts?: string | null;
  missing_windows?: number;
  rows_per_minute?: number;
  eta_seconds?: number | null;
  throttle?: {
    state?: string;
    paused_until?: string | null;
    tokens_remaining?: number | null;
  };
}

export interface IngestCatchupProvider {
  provider_instance_id?: string;
  devices?: IngestCatchupDevice[];
}

export interface IngestCatchupBody {
  ok?: boolean;
  site_id?: string;
  providers?: IngestCatchupProvider[];
  error?: string;
}

export interface IngestCatchupRow {
  key: string;
  providerInstanceId: string;
  deviceId: string;
  mode: string;
  lastStored: string;
  missingWindows: number;
  rowsPerMinute: string;
  eta: string;
  throttle: string;
}

export type IngestCatchupView =
  | { status: "loading" }
  | { status: "unavailable"; reason: string }
  | { status: "error"; message: string }
  | { status: "ready"; rows: IngestCatchupRow[] };

export function catchupModeLabel(mode: string): string {
  if (mode === "asap") return "ASAP catch-up";
  if (mode === "normal") return "Normal";
  return mode;
}

export function ingestCatchupFromFetch(fetched: OptionalFetch): IngestCatchupView {
  if (fetched.http === "missing") {
    return { status: "unavailable", reason: "Catch-up status is unavailable on this stack." };
  }
  if (fetched.http === "error") {
    return { status: "error", message: fetched.message };
  }
  const body = fetched.body as IngestCatchupBody | null;
  if (!body || body.ok === false) {
    return { status: "error", message: body?.error ?? "Catch-up status request failed." };
  }
  const rows: IngestCatchupRow[] = [];
  for (const provider of body.providers ?? []) {
    const providerId = provider.provider_instance_id ?? "—";
    for (const device of provider.devices ?? []) {
      const deviceId = device.device_id ?? "—";
      rows.push({
        key: `${providerId}:${deviceId}`,
        providerInstanceId: providerId,
        deviceId,
        mode: device.mode ?? "normal",
        lastStored: device.last_stored_ts ?? "—",
        missingWindows: device.missing_windows ?? 0,
        rowsPerMinute:
          device.rows_per_minute != null && Number.isFinite(device.rows_per_minute)
            ? device.rows_per_minute.toFixed(1)
            : "—",
        eta:
          device.eta_seconds != null && device.eta_seconds >= 0
            ? `${Math.ceil(device.eta_seconds / 60)} min`
            : "—",
        throttle: device.throttle?.state ?? "—",
      });
    }
  }
  return { status: "ready", rows };
}
