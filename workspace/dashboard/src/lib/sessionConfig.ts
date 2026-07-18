import { apiFetch } from "./api";

/** openfdd_session_v1 (#515) — mirrors vibe19 session_config.json. */
export type SessionConfig = {
  schema_version: "openfdd_session_v1";
  unit_system: "imperial" | "metric" | "si";
  prefer_web_oat?: boolean;
  chw_leave_max_f?: number;
  role_map?: Record<string, Record<string, string>>;
  params?: Record<string, Record<string, number>>;
};

export type SessionConfigGetResponse = {
  ok?: boolean;
  error?: string;
  persisted?: boolean;
  config?: SessionConfig;
};

export type SessionConfigPutResponse = {
  ok?: boolean;
  error?: string;
  config?: SessionConfig;
  warnings?: string[];
  applied_role_map?: { equipment_id: string; ok: boolean }[];
};

export function emptySessionConfig(): SessionConfig {
  return {
    schema_version: "openfdd_session_v1",
    unit_system: "imperial",
    prefer_web_oat: true,
    role_map: {},
    params: {},
  };
}

/** Slider state (rule → param → value) from a loaded session config. */
export function sessionConfigToParamOverrides(
  config: SessionConfig | undefined | null,
): Record<string, Record<string, number>> {
  const out: Record<string, Record<string, number>> = {};
  for (const [ruleId, params] of Object.entries(config?.params ?? {})) {
    const clean: Record<string, number> = {};
    for (const [key, value] of Object.entries(params ?? {})) {
      if (typeof value === "number" && Number.isFinite(value)) clean[key] = value;
    }
    if (Object.keys(clean).length) out[ruleId] = clean;
  }
  return out;
}

/** Session config JSON from current slider state (export / save). */
export function buildSessionConfig(
  paramOverrides: Record<string, Record<string, number>>,
  unitSystem: SessionConfig["unit_system"],
  base?: SessionConfig | null,
): SessionConfig {
  return {
    ...(base ?? emptySessionConfig()),
    schema_version: "openfdd_session_v1",
    unit_system: unitSystem,
    params: Object.fromEntries(
      Object.entries(paramOverrides).filter(([, p]) => Object.keys(p).length > 0),
    ),
  };
}

export function parseSessionConfigFile(text: string): SessionConfig {
  const raw: unknown = JSON.parse(text);
  if (typeof raw !== "object" || raw === null) {
    throw new Error("session config must be a JSON object");
  }
  const cfg = raw as Partial<SessionConfig>;
  if (cfg.schema_version && cfg.schema_version !== "openfdd_session_v1") {
    throw new Error(`schema_version must be openfdd_session_v1, got ${cfg.schema_version}`);
  }
  return { ...emptySessionConfig(), ...cfg, schema_version: "openfdd_session_v1" };
}

export async function fetchSessionConfig(): Promise<SessionConfigGetResponse> {
  return apiFetch<SessionConfigGetResponse>("/api/fdd/session-config");
}

export async function saveSessionConfig(
  config: SessionConfig,
  buildingId?: string,
): Promise<SessionConfigPutResponse> {
  return apiFetch<SessionConfigPutResponse>("/api/fdd/session-config", {
    method: "PUT",
    body: JSON.stringify(buildingId ? { building_id: buildingId, config } : config),
  });
}

export function downloadSessionConfig(config: SessionConfig) {
  const blob = new Blob([JSON.stringify(config, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "session_config.json";
  a.click();
  URL.revokeObjectURL(url);
}
