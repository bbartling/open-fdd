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
  polling: boolean;
  created_at: string;
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
}

export interface FaultDefinition {
  fault_id: string;
  name: string;
  description: string | null;
  severity: string;
  category: string;
  equipment_types: string[] | null;
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
}

export interface Capabilities {
  version: string;
  features: {
    websocket: boolean;
    fault_state: boolean;
    jobs: boolean;
    bacnet_write: boolean;
  };
}

export interface WsEvent {
  type: "event" | "pong" | "error";
  topic?: string;
  ts?: string;
  correlation_id?: string | null;
  data?: Record<string, unknown>;
  message?: string;
}
