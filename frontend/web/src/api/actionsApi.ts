import { apiFetch } from "./client";

export type ActionStatus = "running" | "ok" | "fail" | string;

export interface ActionEntry {
  id: string;
  kind: string;
  label: string;
  started_at: string;
  finished_at?: string | null;
  duration_ms?: number | null;
  status: ActionStatus;
  detail?: Record<string, unknown> | null;
}

export interface ActionsListResponse {
  ok?: boolean;
  count?: number;
  actions?: ActionEntry[];
  error?: string;
}

export async function listActions(limit = 10): Promise<ActionEntry[]> {
  const body = await apiFetch<ActionsListResponse>(
    `/api/actions?limit=${encodeURIComponent(String(limit))}`,
  );
  return Array.isArray(body.actions) ? body.actions : [];
}

export async function deleteAction(id: string): Promise<void> {
  await apiFetch<{ ok?: boolean }>(`/api/actions/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export async function clearActions(): Promise<void> {
  await apiFetch<{ ok?: boolean }>("/api/actions", { method: "DELETE" });
}

/** Prefer the newest running action; else null. */
export function latestRunningAction(
  actions: ActionEntry[],
  kinds?: string[],
): ActionEntry | null {
  for (const a of actions) {
    if (a.status !== "running") continue;
    if (kinds && kinds.length && !kinds.includes(a.kind)) continue;
    return a;
  }
  return null;
}

export function formatDurationMs(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)} s`;
  const m = Math.floor(s / 60);
  const rem = s - m * 60;
  return `${m}m ${rem.toFixed(0)}s`;
}

export function statusIndicator(status: ActionStatus): string {
  switch (status) {
    case "running":
      return "⏳";
    case "ok":
      return "✅";
    case "fail":
      return "❌";
    default:
      return "•";
  }
}

/** Operator-facing status label (ok → Passed, fail → Failed). */
export function statusLabel(status: ActionStatus): string {
  switch (status) {
    case "running":
      return "Running";
    case "ok":
      return "Passed";
    case "fail":
      return "Failed";
    default:
      return String(status);
  }
}
