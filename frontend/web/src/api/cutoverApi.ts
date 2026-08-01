import { apiFetch } from "./client";

export type UiGeneration = "streamlit" | "react";

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
