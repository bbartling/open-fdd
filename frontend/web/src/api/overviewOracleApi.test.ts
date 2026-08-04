import { describe, expect, it, vi, beforeEach } from "vitest";
import { downloadRowsCsv, fetchOverviewVibe19 } from "./overviewOracleApi";

vi.mock("./client", () => ({
  apiFetch: vi.fn(),
}));

import { apiFetch } from "./client";

describe("fetchOverviewVibe19", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset();
  });

  it("POSTs building_id to overview-oracle", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      building_id: "BUILDING_100",
      source: "vibe19-pandas-oracle",
      elapsed_s: 1,
      equipment_count: 1,
      equipment_ids: ["AHU_1"],
      has_weather: false,
      span: { start: null, end: null },
      motor_weekly: { caption: "", plants: [], table: [] },
      mech_cooling: {
        caption: "",
        figure: null,
        bins: [],
        coverage: [],
        n_included: null,
        n_excluded: null,
      },
      economizer_weather: { caption: "", table: [] },
      economizer_free_cooling: {
        caption: "",
        metrics: [],
        delta_scatter: null,
        mat_residual: null,
        temps_overlay: null,
        overlay_equipment_id: null,
        skipped: [],
      },
      bas_vs_web_oat: {
        caption: "",
        overlay: null,
        histogram: null,
        oat_err: 5,
      },
      devices_by_type: [],
    });
    const out = await fetchOverviewVibe19({
      building_id: "BUILDING_100",
      bare_min_occ_hours_week: 72,
    });
    expect(apiFetch).toHaveBeenCalledWith("/api/overview-oracle/vibe19", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: expect.stringContaining("BUILDING_100"),
    });
    expect(out.ok).toBe(true);
    expect(out.equipment_count).toBe(1);
  });
});

describe("downloadRowsCsv", () => {
  it("creates a CSV blob download", () => {
    const clicks: string[] = [];
    const createObjectURL = vi.fn(() => "blob:test");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
    const click = vi.fn();
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      if (tag === "a") {
        return {
          set href(v: string) {
            clicks.push(v);
          },
          set download(v: string) {
            clicks.push(v);
          },
          click,
        } as unknown as HTMLAnchorElement;
      }
      return document.createElement(tag);
    });
    downloadRowsCsv("x.csv", [{ a: 1, b: "x,y" }]);
    expect(createObjectURL).toHaveBeenCalled();
    expect(click).toHaveBeenCalled();
    expect(clicks).toContain("x.csv");
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });
});
