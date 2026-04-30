export const openClawGatewayBase =
  import.meta.env.VITE_OPENFDDCLAW_GATEWAY_BASE
  ?? import.meta.env.VITE_OPENCLAW_GATEWAY_BASE
  ?? "http://127.0.0.1:18789";

export type OpenClawCronApiPayload = {
  name: string;
  cron: string;
  tz: string;
  session: "isolated" | "main";
  message: string;
  failureDestination?: string;
  alertOnSkipped?: boolean;
  idempotencyKey?: string;
  reconcileTag?: string;
  correlationIdPrefix?: string;
};

export type OpenClawCronEndpointPreset = {
  id: string;
  label: string;
  endpointPath: string;
  notes: string;
};

export const OPENCLAW_CRON_ENDPOINT_PRESETS: OpenClawCronEndpointPreset[] = [
  {
    id: "mcp-openclaw-ops-templates",
    label: "MCP Open-FDD Claw ops template endpoint",
    endpointPath: "tools/openclaw_ops_templates",
    notes:
      "Existing backend route: returns generated ops commands/templates. For actual cron-job creation, deploy and use a relay endpoint.",
  },
  {
    id: "custom-relay",
    label: "Custom relay endpoint",
    endpointPath: "api/openfdd/openclaw/cron/create",
    notes:
      "Use this only when your deployment provides a relay route that creates jobs from payload: name, cron, tz, session, message (+ optional failureDestination, alertOnSkipped, idempotencyKey, reconcileTag, correlationIdPrefix).",
  },
];

const DEFAULT_API_TIMEOUT_MS = 15_000;

export function buildCronApiPreview(params: {
  endpointPath: string;
  token?: string;
  payload: OpenClawCronApiPayload;
}): string {
  const endpointPath = params.endpointPath.trim();
  const url = `${openClawGatewayBase.replace(/\/+$/, "")}/${endpointPath.replace(/^\/+/, "")}`;
  const headerLine = params.token?.trim()
    ? '  -H "Authorization: Bearer <REDACTED_TOKEN>" \\\n'
    : "";
  const payloadJson = JSON.stringify(params.payload, null, 2);
  return [
    `curl -X POST "${url}" \\`,
    '  -H "Content-Type: application/json" \\',
    `${headerLine}  --data-binary @- <<'EOF'`,
    payloadJson,
    "EOF",
  ].join("\n");
}

export async function createCronJobViaApi(params: {
  endpointPath: string;
  token?: string;
  payload: OpenClawCronApiPayload;
  timeoutMs?: number;
}): Promise<{ ok: boolean; status: number; body: string }> {
  const endpointPath = params.endpointPath.trim();
  if (!endpointPath) {
    throw new Error("Missing endpoint path.");
  }
  const url = `${openClawGatewayBase.replace(/\/+$/, "")}/${endpointPath.replace(/^\/+/, "")}`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (params.token?.trim()) {
    headers.Authorization = `Bearer ${params.token.trim()}`;
  }
  const timeoutMs = Number.isFinite(params.timeoutMs) ? Number(params.timeoutMs) : DEFAULT_API_TIMEOUT_MS;
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), Math.max(1, timeoutMs));
  try {
    const res = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify(params.payload),
      signal: controller.signal,
    });
    const body = await res.text();
    return { ok: res.ok, status: res.status, body };
  } catch (error) {
    return { ok: false, status: 0, body: String(error) };
  } finally {
    window.clearTimeout(timer);
  }
}

