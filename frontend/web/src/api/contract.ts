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

export interface CapabilitiesResponse {
  ok: boolean;
  contract: ContractMeta;
  capabilities: CapabilityFlags;
}
