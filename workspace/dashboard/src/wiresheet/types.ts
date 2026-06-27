/** Open-FDD Wiresheet graph types — aligned with edge `fdd/wires/schema.rs`. */

export type WiresheetNodeType =
  | "model_site"
  | "model_equipment"
  | "model_point"
  | "driver_point"
  | "fdd_input"
  | "unit_conversion"
  | "quality_check"
  | "sql_rule"
  | "confirmation_timer"
  | "fault_output"
  | "recommendation"
  | "report_section"
  | "comment"
  | "group"
  | "csv_source"
  | "transform_filter"
  | "transform_join"
  | "datafusion_sql"
  | "haystack_tag"
  | "output_trend"
  | "output_alert";

export type WiresheetEdgeType =
  | "maps_to"
  | "feeds"
  | "converts_to"
  | "validates"
  | "assigned_to"
  | "rule_input"
  | "rule_output"
  | "confirms"
  | "reports_to";

export type WiresheetNode = {
  id: string;
  type: WiresheetNodeType | string;
  label: string;
  position: { x: number; y: number };
  config?: Record<string, unknown>;
  source?: string;
  provenance?: Record<string, unknown>;
  validation?: { status?: string; message?: string };
};

export type WiresheetEdge = {
  id: string;
  type: WiresheetEdgeType | string;
  from: string;
  to: string;
};

export type WiresheetGraph = {
  schema_version?: string;
  graph_id: string;
  site_id: string;
  building_id?: string;
  review_status?: string;
  nodes: WiresheetNode[];
  edges: WiresheetEdge[];
  validation_errors?: unknown[];
  validation_warnings?: unknown[];
  execution_status?: string;
  updated_at?: string;
};

export type NodeCatalogEntry = {
  type: WiresheetNodeType | string;
  label: string;
  category: string;
  description: string;
  accent: string;
};
