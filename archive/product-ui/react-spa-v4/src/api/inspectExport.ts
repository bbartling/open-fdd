/**
 * Inspect sample download. The control says JSON, so the file is JSON and
 * contains every plotted series with its name and unit.
 */

export interface InspectExportPoint {
  timestamp: string | null;
  value: number | null;
}

export interface InspectExportSeries {
  name: string | null;
  unit: string | null;
  points: InspectExportPoint[];
}

export interface InspectSampleDocument {
  format: "openfdd.inspect-sample.v1";
  equipment_id: string;
  source: string;
  window: { first: string | null; last: string | null };
  series: InspectExportSeries[];
}

export interface InspectExportTrace {
  name?: string;
  x?: ReadonlyArray<unknown>;
  y?: ReadonlyArray<unknown>;
}

function numericOrNull(value: unknown): number | null {
  if (typeof value === "boolean") return value ? 1 : 0;
  if (value == null || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

function timestampOrNull(value: unknown): string | null {
  if (value == null || value === "") return null;
  return String(value);
}

export function buildInspectSampleExport(input: {
  equipmentId: string;
  source: string;
  window?: { first: string | null; last: string | null };
  traces: ReadonlyArray<InspectExportTrace>;
  unitFor: (name: string) => string | null;
}): InspectSampleDocument {
  const series: InspectExportSeries[] = input.traces.map((trace) => {
    const name =
      typeof trace.name === "string" && trace.name.trim() ? trace.name.trim() : null;
    const xs = trace.x ?? [];
    const ys = trace.y ?? [];
    const n = Math.max(xs.length, ys.length);
    const points: InspectExportPoint[] = [];
    for (let i = 0; i < n; i += 1) {
      points.push({
        timestamp: timestampOrNull(xs[i]),
        value: numericOrNull(ys[i]),
      });
    }
    return {
      name,
      unit: name ? input.unitFor(name) : null,
      points,
    };
  });
  return {
    format: "openfdd.inspect-sample.v1",
    equipment_id: input.equipmentId,
    source: input.source,
    window: {
      first: input.window?.first ?? null,
      last: input.window?.last ?? null,
    },
    series,
  };
}

/** Browser download of one JSON document. */
export function downloadJson(filename: string, body: unknown): void {
  const blob = new Blob([JSON.stringify(body, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = globalThis.document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
