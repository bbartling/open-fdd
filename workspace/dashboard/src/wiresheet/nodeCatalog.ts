import type { NodeCatalogEntry } from "./types";

/** Palette catalog for the Wiresheet studio — HVAC/FDD oriented node library. */
export const NODE_CATEGORIES = [
  "Data Sources",
  "Transforms",
  "Arrow / DataFusion",
  "Haystack",
  "Fault Detection",
  "Outputs",
] as const;

export const NODE_CATALOG: NodeCatalogEntry[] = [
  { type: "driver_point", label: "BACnet Point", category: "Data Sources", description: "Live BACnet object reference", accent: "#3b6de0" },
  { type: "csv_source", label: "CSV Upload", category: "Data Sources", description: "Historian or manual CSV ingest", accent: "#3b6de0" },
  { type: "driver_point", label: "Haystack Ref", category: "Data Sources", description: "Haystack curated point ref", accent: "#2d9a52" },
  { type: "driver_point", label: "Modbus Register", category: "Data Sources", description: "Modbus TCP register map", accent: "#3b6de0" },
  { type: "driver_point", label: "REST API", category: "Data Sources", description: "JSON HTTP polling source", accent: "#3b6de0" },
  { type: "driver_point", label: "Historian", category: "Data Sources", description: "Committed historian table", accent: "#3b6de0" },
  { type: "driver_point", label: "Weather API", category: "Data Sources", description: "Outdoor air / weather feed", accent: "#3b6de0" },

  { type: "transform_filter", label: "Filter", category: "Transforms", description: "Row filter expression", accent: "#7c5cbf" },
  { type: "transform_filter", label: "Aggregate", category: "Transforms", description: "Group-by aggregation", accent: "#7c5cbf" },
  { type: "transform_join", label: "Join", category: "Transforms", description: "Inner/outer join on keys", accent: "#7c5cbf" },
  { type: "transform_join", label: "Merge", category: "Transforms", description: "Column merge by timestamp", accent: "#7c5cbf" },
  { type: "transform_filter", label: "Pivot", category: "Transforms", description: "Wide pivot transform", accent: "#7c5cbf" },
  { type: "unit_conversion", label: "Scale / Unit", category: "Transforms", description: "Unit conversion & scaling", accent: "#7c5cbf" },
  { type: "quality_check", label: "Clamp / Delta", category: "Transforms", description: "Clamp, delta, rolling average", accent: "#7c5cbf" },

  { type: "datafusion_sql", label: "SQL Query", category: "Arrow / DataFusion", description: "Ad-hoc DataFusion SQL", accent: "#c9870a" },
  { type: "sql_rule", label: "SQL Rule", category: "Arrow / DataFusion", description: "Executable FDD SQL rule", accent: "#c9870a" },
  { type: "datafusion_sql", label: "Dataset", category: "Arrow / DataFusion", description: "Named Arrow dataset", accent: "#c9870a" },
  { type: "quality_check", label: "Validation", category: "Arrow / DataFusion", description: "Schema & null checks", accent: "#c9870a" },

  { type: "model_site", label: "Site", category: "Haystack", description: "Haystack site entity", accent: "#2d9a52" },
  { type: "model_equipment", label: "Equipment", category: "Haystack", description: "AHU, VAV, plant equip", accent: "#2d9a52" },
  { type: "model_point", label: "Point", category: "Haystack", description: "Cur / sensor / sp point", accent: "#2d9a52" },
  { type: "haystack_tag", label: "Tag / Marker", category: "Haystack", description: "Haystack tag assignment", accent: "#2d9a52" },

  { type: "sql_rule", label: "Rule", category: "Fault Detection", description: "FDD rule block", accent: "#c53d3d" },
  { type: "fault_output", label: "Fault", category: "Fault Detection", description: "Fault code output", accent: "#c53d3d" },
  { type: "fault_output", label: "Alarm", category: "Fault Detection", description: "Operator alarm", accent: "#c53d3d" },
  { type: "confirmation_timer", label: "Confirmation", category: "Fault Detection", description: "Persistence timer", accent: "#c53d3d" },
  { type: "fdd_input", label: "FDD Input", category: "Fault Detection", description: "Rule input binding", accent: "#c53d3d" },

  { type: "output_trend", label: "Trend", category: "Outputs", description: "Historian trend output", accent: "#0ea5a0" },
  { type: "output_trend", label: "Plot", category: "Outputs", description: "Plotly visualization", accent: "#0ea5a0" },
  { type: "report_section", label: "RCx Report", category: "Outputs", description: "Report section block", accent: "#0ea5a0" },
  { type: "output_alert", label: "Alert", category: "Outputs", description: "Notification output", accent: "#0ea5a0" },
  { type: "recommendation", label: "Dashboard", category: "Outputs", description: "Dashboard tile binding", accent: "#0ea5a0" },
];

export function catalogByCategory(): Map<string, NodeCatalogEntry[]> {
  const map = new Map<string, NodeCatalogEntry[]>();
  for (const cat of NODE_CATEGORIES) map.set(cat, []);
  for (const entry of NODE_CATALOG) {
    const list = map.get(entry.category) ?? [];
    list.push(entry);
    map.set(entry.category, list);
  }
  return map;
}

export function accentForNodeType(type: string): string {
  const hit = NODE_CATALOG.find((e) => e.type === type);
  if (hit) return hit.accent;
  if (type.startsWith("model_") || type.startsWith("haystack")) return "#2d9a52";
  if (type.includes("sql") || type.includes("datafusion")) return "#c9870a";
  if (type.includes("fault") || type.includes("fdd") || type.includes("confirm")) return "#c53d3d";
  if (type.includes("output") || type.includes("report")) return "#0ea5a0";
  if (type.includes("transform") || type.includes("unit") || type.includes("quality")) return "#7c5cbf";
  return "#3b6de0";
}
