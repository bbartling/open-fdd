import { describe, expect, it } from "vitest";
import {
  appendExportQuery,
  canDownloadExport,
  DATA_EXPORT_PANEL_TITLE,
  exportButtonLabel,
  type ExportMeta,
  type ExportMetaItem,
  visibleExports,
} from "./dataExport";

describe("dataExport helpers", () => {
  const baseMeta: ExportMeta = {
    ok: true,
    xlsx_supported: false,
    filters: {
      sites: ["site:demo"],
      buildings: ["building:main"],
      protocols: ["bacnet"],
      equipment: ["5007"],
    },
    exports: [
      {
        id: "historian",
        label: "Historian time series",
        format: "csv",
        path: "/api/export/historian.csv",
        available: true,
      },
      {
        id: "bacnet-overrides",
        label: "BACnet override report",
        format: "csv",
        path: "/api/bacnet/overrides/export",
        available: true,
      },
      {
        id: "rules",
        label: "Rule definitions",
        format: "csv",
        path: "/api/export/rules.csv",
        requires_role: "integrator|agent",
        available: true,
      },
      {
        id: "bench-5007",
        label: "5007 bench smoke data",
        format: "csv",
        path: "/api/export/bench-5007.csv",
        available: false,
      },
    ],
  };

  it("uses Data Export panel title", () => {
    expect(DATA_EXPORT_PANEL_TITLE).toBe("Data Export");
  });

  it("appends filter query params for historian download", () => {
    const path = appendExportQuery("/api/export/historian.csv", {
      hours: 24,
      equipment_id: "5007",
      source_protocol: "bacnet",
    });
    expect(path).toContain("hours=24");
    expect(path).toContain("equipment_id=5007");
    expect(path).toContain("source_protocol=bacnet");
  });

  it("shows historian and BACnet override buttons for operators", () => {
    const items = visibleExports(baseMeta, "operator");
    const ids = items.map((i) => i.id);
    expect(ids).toContain("historian");
    expect(ids).toContain("bacnet-overrides");
    expect(ids).not.toContain("rules");
  });

  it("hides unavailable bench export when smoke artifacts absent", () => {
    const items = visibleExports(baseMeta, "integrator");
    expect(items.some((i) => i.id === "bench-5007")).toBe(false);
  });

  it("shows bench export when available", () => {
    const meta: ExportMeta = {
      ...baseMeta,
      exports: baseMeta.exports.map((e) =>
        e.id === "bench-5007" ? { ...e, available: true, row_count: 48 } : e,
      ),
    };
    const items = visibleExports(meta, "integrator");
    expect(items.some((i) => i.id === "bench-5007")).toBe(true);
  });

  it("labels download buttons for Excel users", () => {
    const item: ExportMetaItem = {
      id: "historian",
      label: "Historian time series",
      format: "csv",
      path: "/api/export/historian.csv",
      row_count: 120,
    };
    expect(exportButtonLabel(item)).toContain("Historian time series");
    expect(exportButtonLabel(item)).toContain("CSV");
  });

  it("blocks integrator-only exports for operators", () => {
    const rules: ExportMetaItem = {
      id: "rules",
      label: "Rule definitions",
      format: "csv",
      path: "/api/export/rules.csv",
      requires_role: "integrator|agent",
      available: true,
    };
    expect(canDownloadExport(rules, "operator")).toBe(false);
    expect(canDownloadExport(rules, "integrator")).toBe(true);
  });
});
