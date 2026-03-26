/** GET /config and PUT /config — platform config (RDF-backed). */
export interface PlatformConfig {
  rule_interval_hours?: number;
  lookback_days?: number;
  rules_dir?: string | null;
  brick_ttl_dir?: string | null;
  bacnet_enabled?: boolean;
  bacnet_scrape_interval_min?: number;
  bacnet_server_url?: string | null;
  bacnet_site_id?: string | null;
  bacnet_gateways?: string | null;
  open_meteo_enabled?: boolean;
  open_meteo_interval_hours?: number;
  open_meteo_latitude?: number;
  open_meteo_longitude?: number;
  open_meteo_timezone?: string | null;
  open_meteo_days_back?: number;
  open_meteo_site_id?: string | null;
  graph_sync_interval_min?: number;
  [key: string]: unknown;
}

export interface Site {
  id: string;
  name: string;
  description: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface Equipment {
  id: string;
  site_id: string;
  name: string;
  description: string | null;
  equipment_type: string | null;
  metadata?: Record<string, unknown> | null;
  feeds_equipment_id: string | null;
  fed_by_equipment_id: string | null;
  created_at: string;
}

export interface Point {
  id: string;
  site_id: string;
  external_id: string;
  brick_type: string | null;
  fdd_input: string | null;
  unit: string | null;
  description: string | null;
  equipment_id: string | null;
  bacnet_device_id: string | null;
  object_identifier: string | null;
  object_name: string | null;
  /** From data model (ofdd:polling in TTL). If true, BACnet scraper polls this point. */
  polling: boolean;
  created_at: string;
}

/** GET /timeseries/latest — latest reading per point (BACnet scraper / weather). */
export interface TimeseriesLatestItem {
  point_id: string;
  external_id: string;
  equipment_id: string | null;
  value: number;
  ts: string | null;
}

export interface FaultState {
  id: string;
  site_id: string;
  equipment_id: string;
  fault_id: string;
  active: boolean;
  last_changed_ts: string;
  last_evaluated_ts: string | null;
  context: Record<string, unknown> | null;
  /** BACnet device instance ID when available (from points for this equipment). */
  bacnet_device_id?: string | null;
}

export interface FaultDefinition {
  fault_id: string;
  name: string;
  description: string | null;
  severity: string;
  category: string;
  equipment_types: string[] | null;
}

/** GET /faults/bacnet-devices — from data model (points + equipment). */
export interface BacnetDevice {
  site_id: string;
  site_name: string;
  bacnet_device_id: string;
  equipment_id: string | null;
  equipment_name: string;
  equipment_type: string | null;
}

export interface FddRunStatus {
  last_run: {
    run_ts: string;
    status: string;
    sites_processed: number;
    faults_written: number;
  } | null;
}

export interface HealthStatus {
  status: string;
  serialization_status?: string | null;
  graph_loaded?: boolean | null;
  graph_serialization?: {
    last_ok?: boolean | null;
    last_error?: string | null;
    last_serialization_at?: string | null;
    current_time?: string | null;
    path_resolved?: string | null;
  } | null;
  last_fdd_run?: {
    run_ts: string;
    status: string;
    sites_processed: number;
    faults_written: number;
  } | null;
}

/** GET /data-model/export row (simplified for UI) */
export interface DataModelExportRow {
  point_id?: string | null;
  bacnet_device_id?: string | null;
  object_identifier?: string | null;
  object_name?: string | null;
  site_id?: string | null;
  site_name?: string | null;
  equipment_id?: string | null;
  equipment_name?: string | null;
  equipment_metadata?: Record<string, unknown> | null;
  engineering?: Record<string, unknown> | null;
  external_id?: string | null;
  brick_type?: string | null;
  rule_input?: string | null;
  unit?: string | null;
  polling?: boolean;
  [key: string]: unknown;
}

/** PUT /data-model/import body */
export interface DataModelImportBody {
  points: DataModelExportRow[];
  equipment?: unknown[];
}

/** PUT /data-model/import response */
export interface DataModelImportResponse {
  created?: number;
  updated?: number;
  total?: number;
  warnings?: string[];
}

/** POST /data-model/sparql response */
export interface SparqlResponse {
  bindings: Record<string, string | null>[];
}

export interface Capabilities {
  version: string;
  features: {
    websocket: boolean;
    fault_state: boolean;
    jobs: boolean;
    bacnet_write: boolean;
  };
  /** Always false in core Open-FDD; use external agents with /model-context and /mcp/manifest. */
  ai_available: boolean;
  /** Core API does not embed an LLM; value is always "disabled". */
  ai_backend: "disabled";
}

/** POST /bacnet/server_hello response (API returns { ok, body? } where body is JSON-RPC). */
export interface MqttBridgeStatus {
  enabled: boolean;
  connected: boolean;
  broker_url: string | null;
  last_error: string | null;
}

export interface BacnetServerHelloResponse {
  ok: boolean;
  status_code?: number;
  body?: {
    result?: { message?: string; mqtt_bridge?: MqttBridgeStatus };
    error?: unknown;
  };
  error?: string;
}

export interface WsEvent {
  type: "event" | "pong" | "error";
  topic?: string;
  ts?: string;
  correlation_id?: string | null;
  data?: Record<string, unknown>;
  message?: string;
}

/** GET /analytics/fault-summary */
export interface FaultSummaryResponse {
  site_id: string | null;
  period: { start: string; end: string };
  by_fault_id: { fault_id: string; count: number; flag_sum: number }[];
  total_faults: number;
  /** Distinct (site, equipment, fault) active in range; not summed. */
  active_in_period: number;
}

/** GET /analytics/faults-by-equipment */
export interface FaultsByEquipmentResponse {
  site_id: string | null;
  period: { start: string; end: string };
  by_equipment: {
    site_id: string;
    equipment_id: string;
    equipment_name: string;
    bacnet_device_id: string | null;
    active_fault_count: number;
  }[];
}

/** GET /analytics/fault-timeseries */
export interface FaultTimeseriesResponse {
  site_id: string | null;
  period: { start: string; end: string };
  bucket: string;
  series: { time: string; metric: string; value: number }[];
  /** Present when the request scoped by equipment (Plots device overlay). */
  equipment_ids?: string[];
}

/** GET /analytics/fault-results-series — distinct fault × site × equipment for data preview selector */
export interface FaultResultsSeriesResponse {
  series: { fault_id: string; site_id: string; equipment_id: string; label: string }[];
  period: { start: string; end: string };
}

/** GET /analytics/fault-results-raw — last N rows for Excel-style data preview */
export interface FaultResultsRawResponse {
  rows: {
    ts: string;
    site_id: string;
    equipment_id: string;
    fault_id: string;
    flag_value: number;
    evidence: unknown;
  }[];
  count: number;
}

/** GET /analytics/system/host */
export interface SystemHostResponse {
  hosts: {
    hostname: string;
    ts: string;
    mem_used_gb: number;
    mem_available_gb: number;
    mem_total_gb: number;
    swap_used_gb: number;
    load_1: number;
    load_5: number;
    load_15: number;
  }[];
}

/** GET /analytics/system/host/series */
export interface SystemHostSeriesResponse {
  series: { time: string; metric: string; value: number; hostname?: string }[];
}

/** GET /analytics/system/containers */
export interface SystemContainersResponse {
  containers: {
    container_name: string;
    ts: string;
    cpu_pct: number;
    mem_mb: number;
    mem_pct: number | null;
    pids: number;
  }[];
}

/** GET /analytics/system/containers/series */
export interface SystemContainersSeriesResponse {
  series: { time: string; metric: string; value: number; type: "mem_mb" | "cpu_pct" }[];
}

/** GET /analytics/system/disk */
export interface SystemDiskResponse {
  disks: {
    hostname: string;
    mount_path: string;
    ts: string;
    used_gb: number;
    free_gb: number;
    total_gb: number;
    used_pct: number;
  }[];
}

/** Point-timeseries payload (same series shape as fault-timeseries for charts). */
export interface PointTimeseriesResponse {
  period: { start: string; end: string };
  series: { time: string; metric: string; value: number }[];
  point_labels?: Record<string, string>;
}

/** Last N fault_results rows (for tabular display in chat). */
export interface FaultResultsSampleResponse {
  rows: {
    ts: string;
    site_id: string;
    equipment_id: string;
    fault_id: string;
    flag_value: number;
    evidence?: unknown;
  }[];
  count: number;
}

