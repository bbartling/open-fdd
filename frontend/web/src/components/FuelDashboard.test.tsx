import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { FuelDashboard } from "./FuelDashboard";
import { apiFetch } from "../api/client";

vi.mock("../api/client", () => ({
  apiFetch: vi.fn(),
}));

vi.mock("./widgets/PlotlyHost", () => ({
  PlotlyHost: () => <div data-testid="plotly-stub" />,
}));

const OTHER = "w5f-other";
const EMPTY = "w5f-empty";
const METERED = "w5f-metered";

describe("FuelDashboard site scope", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset();
  });

  it("shows no meters for the selected site and does not paint another campus", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path.includes("building_id=w5f-other") || !path.includes(`building_id=${EMPTY}`)) {
        return {
          ok: true,
          scope: "unscoped",
          campuses: [{ campus_id: OTHER, label: "Other Campus" }],
          active: { campus_id: OTHER, label: "Other Campus" },
        };
      }
      return {
        ok: true,
        status: "no_meters",
        scope: "site",
        building_id: EMPTY,
        campuses: [{ campus_id: OTHER, label: "Other Campus" }],
        active: { campus_id: OTHER, label: "Other Campus" },
        count: 0,
      };
    });

    render(<FuelDashboard siteId={EMPTY} />);

    expect((await screen.findByTestId("fuel-no-meters")).textContent).toContain(
      "This site has no meters.",
    );
    expect(screen.queryByText("Other Campus")).toBeNull();
    expect(screen.queryByTestId("fuel-campus-locked")).toBeNull();
    const calls = vi.mocked(apiFetch).mock.calls.map(([path]) => String(path));
    expect(calls.some((path) => path.includes(`/api/analytics/fuel`))).toBe(false);
    expect(calls.every((path) => path.includes(`building_id=${EMPTY}`))).toBe(true);
  });

  it("requests analytics only for the active site", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string, init?: RequestInit) => {
      if (String(path).startsWith("/api/fuel/campus")) {
        return {
          ok: true,
          status: "ok",
          scope: "site",
          building_id: METERED,
          campuses: [{ campus_id: METERED, label: "Metered" }],
          active: { campus_id: METERED, label: "Metered" },
          count: 1,
        };
      }
      const body = JSON.parse(String(init?.body ?? "{}")) as {
        building_id?: string;
        campus_id?: string;
      };
      expect(body.building_id).toBe(METERED);
      expect(body.campus_id).toBe(METERED);
      return {
        ok: true,
        status: "ok",
        query_version: body.campus_id,
        engine: "rust-fuel",
        rows: [],
        warnings: [],
        campus_id: METERED,
      };
    });

    render(<FuelDashboard siteId={METERED} />);
    expect(await screen.findByTestId("fuel-campus-locked")).toBeTruthy();
    expect(screen.queryByText("Other Campus")).toBeNull();
    await waitFor(() => {
      const analyticCalls = vi
        .mocked(apiFetch)
        .mock.calls.filter(([path]) => String(path).includes("/api/analytics/fuel"));
      expect(analyticCalls.length).toBeGreaterThan(0);
    });
  });

  it("does not load a campus when no site is locked", async () => {
    render(<FuelDashboard />);
    expect(await screen.findByTestId("fuel-site-required")).toBeTruthy();
    expect(vi.mocked(apiFetch)).not.toHaveBeenCalled();
  });
});
