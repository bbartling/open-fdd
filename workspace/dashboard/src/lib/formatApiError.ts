/** Pull a human-readable message from bridge/commission API errors. */
function mapForbidden(msg: string): string {
  if (msg === "forbidden") {
    return "Not permitted for your login role — sign in with an account that has access.";
  }
  if (msg.includes("OFDD_ENABLE_BACNET_DISCOVERY_MUTATIONS") || msg.includes("OFDD_DISABLE_BACNET_DISCOVERY_MUTATIONS")) {
    return "Driver registry updates are disabled on this server (read-only monitor mode). Recreate the bridge after updating site config.";
  }
  if (msg.includes("BACnet model/driver mutations require integrator")) {
    return "Cannot save discovered points to the driver — sign in as integrator, or ask ops to enable commissioning on the bridge.";
  }
  return msg;
}

function formatDetailObject(obj: Record<string, unknown>): string {
  const message = typeof obj.message === "string" ? mapForbidden(obj.message) : "";
  const hint = typeof obj.hint === "string" ? obj.hint.trim() : "";
  if (message && hint) return `${message} ${hint}`;
  if (message) return message;
  if (typeof obj.error === "string") return mapForbidden(obj.error);
  if (typeof obj.detail === "string") return mapForbidden(obj.detail);
  return "";
}

export function formatApiError(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error);
  try {
    const body = JSON.parse(raw) as { detail?: unknown };
    const detail = body.detail;
    if (typeof detail === "string") return mapForbidden(detail);
    if (detail && typeof detail === "object") {
      const formatted = formatDetailObject(detail as Record<string, unknown>);
      if (formatted) return formatted;
    }
  } catch {
    /* not JSON */
  }
  if (raw.includes("commission agent unreachable")) {
    return "BACnet commission agent is down — run ./scripts/run_local.sh restart";
  }
  return mapForbidden(raw);
}
