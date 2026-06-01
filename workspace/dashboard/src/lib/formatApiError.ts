/** Pull a human-readable message from bridge/commission API errors. */
function mapForbidden(msg: string): string {
  if (msg === "forbidden") {
    return "Not permitted for your login role — sign in with an account that has access.";
  }
  return msg;
}

export function formatApiError(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error);
  try {
    const body = JSON.parse(raw) as { detail?: unknown };
    const detail = body.detail;
    if (typeof detail === "string") return mapForbidden(detail);
    if (detail && typeof detail === "object") {
      const obj = detail as Record<string, unknown>;
      if (typeof obj.error === "string") return mapForbidden(obj.error);
      if (typeof obj.detail === "string") return mapForbidden(obj.detail);
      if (typeof obj.message === "string") return mapForbidden(obj.message);
    }
  } catch {
    /* not JSON */
  }
  if (raw.includes("commission agent unreachable")) {
    return "BACnet commission agent is down — run ./scripts/run_local.sh restart";
  }
  return mapForbidden(raw);
}
