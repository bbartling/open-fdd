/** Pull a human-readable message from bridge/commission API errors. */
export function formatApiError(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error);
  try {
    const body = JSON.parse(raw) as { detail?: unknown };
    const detail = body.detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object") {
      const obj = detail as Record<string, unknown>;
      if (typeof obj.error === "string") return obj.error;
      if (typeof obj.detail === "string") return obj.detail;
      if (typeof obj.message === "string") return obj.message;
    }
  } catch {
    /* not JSON */
  }
  if (raw.includes("commission agent unreachable")) {
    return "BACnet commission agent is down — run ./scripts/run_local.sh restart";
  }
  return raw;
}
