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
    id: "native-openclaw-cron",
    label: "Native Open-FDD Claw cron API (recommended)",
    endpointPath: "api/cron/jobs",
    notes:
      "Expected payload shape: name, cron, tz, session, message (+ optional failureDestination, alertOnSkipped, idempotencyKey, reconcileTag, correlationIdPrefix).",
  },
  {
    id: "custom-relay",
    label: "Custom relay endpoint",
    endpointPath: "api/openfdd/openclaw/cron/create",
    notes: "Use this if you deploy an adapter route in front of Open-FDD Claw (OpenClaw-inspired gateway).",
  },
];

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
  const res = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(params.payload),
  });
  const body = await res.text();
  return { ok: res.ok, status: res.status, body };
}

