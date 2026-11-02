import { apiFetch } from "./client";

/** Drop a CSV guest lease when the operator leaves that building. Best-effort. */
export function leaveBuildingSession(buildingId: string): void {
  const id = buildingId.trim();
  if (!id) return;
  void apiFetch("/api/sessions/building/leave", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ building_id: id }),
  }).catch(() => {
    // The idle timer still drops the lease if this call fails.
  });
}
