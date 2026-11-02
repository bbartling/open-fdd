/** Mirrors `openfdd.api.contract.v1` — see services/central/src/contract.rs */

export const CONTRACT_VERSION = "openfdd.api.contract.v1";

export interface ErrorBody {
  code: string;
  message: string;
  details?: unknown;
  retryable: boolean;
  request_id: string;
}

export interface ApiErrorEnvelope {
  error: ErrorBody;
}

export interface ContractMeta {
  contract_version: string;
  compatibility: string;
  timestamps: string;
  missing_float: string;
  revision_header: string;
  idempotency_header: string;
  request_id_header: string;
  error_envelope: string;
  job_run_status: string[];
  async_ops: string;
  react_ui_flag: string;
}

export interface CapabilityFlags {
  lab?: boolean;
  fdd_registry?: boolean;
  fdd_equipment?: boolean;
  fdd_results?: boolean;
  fdd_series?: boolean;
  session_config?: boolean;
  csv_package?: boolean;
  reports?: boolean;
  export?: boolean;
  data_management?: boolean;
  host_stats?: boolean;
  faults?: boolean;
  health_stack?: boolean;
  fdd_rules_authoring?: boolean;
  fdd_schema?: boolean;
  analytics?: boolean;
  jobs?: boolean;
  react_ui?: boolean;
  [key: string]: boolean | undefined;
}

/** Connector capability values returned inside the authenticated aggregate. */
export type ConnectorProtocol = "bacnet" | "modbus" | "haystack" | "rest" | "mqtt";

export type CapabilityState =
  | "disabled"
  | "not_configured"
  | "checking"
  | "ready"
  | "degraded"
  | "unreachable"
  | "auth_failure"
  | "incompatible"
  | "stale"
  | "unknown";

export type DeliveryStatus = CapabilityState;

export interface ConnectorCapability {
  protocol: ConnectorProtocol | string;
  compiled: boolean;
  configured: boolean;
  enabled: boolean;
  readiness: CapabilityState | string;
  source_health: CapabilityState | string;
  mqtt_connection: DeliveryStatus | string;
  durable_delivery: DeliveryStatus | string;
  supported_actions?: string[];
  detail?: string | null;
}

export interface ConnectorHelloResponse {
  schema: string;
  version?: {
    service?: string;
    build?: string;
    contract?: string;
  };
  compiled_protocols?: ConnectorProtocol[];
  connectors?: ConnectorCapability[];
  recipe?: {
    declared?: string | null;
    configured_services?: string[];
    observed_services?: string[];
    unobserved_services?: string[];
    reconciliation?: string;
  };
  observed_at?: string;
}

export interface UpstreamCapability {
  edge_id?: string;
  address?: string;
  state?: CapabilityState | string;
  hello?: ConnectorHelloResponse | null;
  error?: string | null;
  last_success_at?: string | null;
}

export interface CapabilitiesAggregate {
  schema?: string;
  central?: ConnectorHelloResponse;
  upstreams?: UpstreamCapability[];
  recipe?: ConnectorHelloResponse["recipe"];
  diagnostic?: string | null;
  generated_at?: string;
  observed_at?: string;
}

export interface CapabilitiesResponse {
  ok: boolean;
  contract: ContractMeta;
  capabilities: CapabilityFlags;
  connector_capabilities?: CapabilitiesAggregate;
}
