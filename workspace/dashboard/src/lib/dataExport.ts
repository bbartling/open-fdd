export type ExportMetaItem = {
  id: string;
  label: string;
  format: string;
  path: string;
  row_count?: number;
  available?: boolean;
  requires_role?: string;
  data_source_label?: string;
};

export type ExportMeta = {
  ok: boolean;
  exports: ExportMetaItem[];
  filters: {
    sites: string[];
    buildings: string[];
    protocols: string[];
    equipment: string[];
  };
  xlsx_supported: boolean;
  xlsx_note?: string;
};

export type ExportFilters = {
  hours?: number;
  start?: string;
  end?: string;
  site_id?: string;
  building_id?: string;
  equipment_id?: string;
  source_protocol?: string;
};

export const DATA_EXPORT_PANEL_TITLE = "Data Export";

export function buildExportQuery(filters: ExportFilters): string {
  const params = new URLSearchParams();
  if (filters.hours != null && filters.hours > 0) {
    params.set("hours", String(filters.hours));
  }
  if (filters.start?.trim()) params.set("start", filters.start.trim());
  if (filters.end?.trim()) params.set("end", filters.end.trim());
  if (filters.site_id?.trim()) params.set("site_id", filters.site_id.trim());
  if (filters.building_id?.trim()) params.set("building_id", filters.building_id.trim());
  if (filters.equipment_id?.trim()) params.set("equipment_id", filters.equipment_id.trim());
  if (filters.source_protocol?.trim()) params.set("source_protocol", filters.source_protocol.trim());
  return params.toString();
}

export function appendExportQuery(path: string, filters: ExportFilters): string {
  const q = buildExportQuery(filters);
  if (!q) return path;
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}${q}`;
}

export function canDownloadExport(item: ExportMetaItem, role: string | null): boolean {
  const req = item.requires_role || "";
  if (req.includes("integrator") && role !== "integrator" && role !== "agent") {
    return false;
  }
  return item.available !== false;
}

export function visibleExports(meta: ExportMeta, role: string | null): ExportMetaItem[] {
  return meta.exports.filter((item) => canDownloadExport(item, role));
}

export function exportButtonLabel(item: ExportMetaItem): string {
  const rows =
    item.row_count != null && item.row_count > 0 ? ` (~${item.row_count.toLocaleString()} rows)` : "";
  return `Download ${item.label} CSV${rows}`;
}
