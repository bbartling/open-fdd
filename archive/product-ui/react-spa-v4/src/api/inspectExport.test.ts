import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { buildInspectSampleExport, downloadJson } from "./inspectExport";
import { resolveRoleUnit } from "./roleUnits";

function unitFor(name: string): string | null {
  const unit = resolveRoleUnit(name);
  return unit ? unit : null;
}

describe("inspect sample export", () => {
  it("includes every selected series with name, unit, and every point", () => {
    const doc = buildInspectSampleExport({
      equipmentId: "AHU_1",
      source: "POST /api/analytics/inspect",
      window: {
        first: "2026-03-16T00:40:00Z",
        last: "2026-03-16T00:45:00Z",
      },
      traces: [
        {
          name: "sat",
          x: ["2026-03-16T00:40:00Z", "2026-03-16T00:45:00Z"],
          y: [55, 56],
        },
        {
          name: "duct_static",
          x: ["2026-03-16T00:40:00Z", "2026-03-16T00:45:00Z"],
          y: [0.8, 0.9],
        },
        {
          name: "custom_role",
          x: ["2026-03-16T00:40:00Z"],
          y: [1],
        },
      ],
      unitFor,
    });
    expect(doc.format).toBe("openfdd.inspect-sample.v1");
    expect(doc.equipment_id).toBe("AHU_1");
    expect(doc.source).toBe("POST /api/analytics/inspect");
    expect(doc.window).toEqual({
      first: "2026-03-16T00:40:00Z",
      last: "2026-03-16T00:45:00Z",
    });
    expect(doc.series.map((series) => series.name)).toEqual([
      "sat",
      "duct_static",
      "custom_role",
    ]);
    expect(doc.series[0]?.unit).toBe("°F");
    expect(doc.series[1]?.unit).toBe("in. w.c.");
    expect(doc.series[2]?.unit).toBeNull();
    expect(doc.series[0]?.points).toEqual([
      { timestamp: "2026-03-16T00:40:00Z", value: 55 },
      { timestamp: "2026-03-16T00:45:00Z", value: 56 },
    ]);
    expect(doc.series[1]?.points).toEqual([
      { timestamp: "2026-03-16T00:40:00Z", value: 0.8 },
      { timestamp: "2026-03-16T00:45:00Z", value: 0.9 },
    ]);
    expect(doc.series[2]?.points).toEqual([
      { timestamp: "2026-03-16T00:40:00Z", value: 1 },
    ]);
  });
});

describe("downloadJson", () => {
  const origCreate = URL.createObjectURL;
  const origRevoke = URL.revokeObjectURL;

  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => "blob:inspect") as unknown as typeof URL.createObjectURL;
    URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;
  });

  afterEach(() => {
    URL.createObjectURL = origCreate;
    URL.revokeObjectURL = origRevoke;
    vi.restoreAllMocks();
  });

  it("writes an application/json blob", () => {
    const click = vi.fn();
    const anchor = { click, href: "", download: "" };
    const orig = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      if (tag === "a") return anchor as unknown as HTMLAnchorElement;
      return orig(tag);
    });
    downloadJson("AHU_1_inspect.json", { format: "openfdd.inspect-sample.v1" });
    const blob = vi.mocked(URL.createObjectURL).mock.calls[0]?.[0] as Blob;
    expect(blob).toBeInstanceOf(Blob);
    expect(blob.type).toBe("application/json");
    expect(anchor.download).toBe("AHU_1_inspect.json");
    expect(click).toHaveBeenCalled();
  });
});