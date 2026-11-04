import { apiFetch } from "./client";

export type UiGeneration = "react";

export interface GenerationStatus {
  ok: boolean;
  generation: UiGeneration;
  source: string;
  default_generation: UiGeneration;
  production_default_flipped: boolean;
  sticky_cookie: string;
}

export async function getUiGeneration(): Promise<GenerationStatus> {
  return apiFetch<GenerationStatus>("/api/ui/generation");
}

export async function setUiGeneration(
  generation: UiGeneration,
  reason?: string,
): Promise<Record<string, unknown>> {
  return apiFetch("/api/ui/generation", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ generation, reason }),
  });
}

export async function getMigrationMetrics(): Promise<Record<string, unknown>> {
  return apiFetch("/api/ui/migration-metrics");
}

export async function postMigrationEvent(
  event: string,
  reasonCode?: string,
  uiGeneration?: UiGeneration,
): Promise<Record<string, unknown>> {
  return apiFetch("/api/ui/migration-event", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      event,
      reason_code: reasonCode,
      ui_generation: uiGeneration,
    }),
  });
}
