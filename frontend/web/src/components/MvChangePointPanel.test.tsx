import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MvChangePointPanel } from "./MvChangePointPanel";
import { postMvChangePoint } from "../api/analyticsApi";

vi.mock("../api/analyticsApi", () => ({
  postMvChangePoint: vi.fn(),
}));

vi.mock("./widgets/PlotlyHost", () => ({
  PlotlyHost: () => <div data-testid="plotly-stub" />,
}));

describe("MvChangePointPanel", () => {
  beforeEach(() => {
    vi.mocked(postMvChangePoint).mockReset();
  });

  it("posts the inline demo series and shows the returned savings", async () => {
    vi.mocked(postMvChangePoint).mockResolvedValue({
      schema_version: "analytics-envelope-v1",
      query_version: "mv-change-point-v1",
      generated_at: "2026-01-01T00:00:00Z",
      engine: "central-analytics-v1",
      warnings: [],
      rows: [
        {
          period: "2024-01",
          period_kind: "reporting",
          energy: 1,
          degree_days: 2,
          predicted: 3,
          savings: 2,
        },
      ],
      equipment: [],
      points: [
        { period: "2024-01", x: 2, y: 1, period_kind: "reporting", y_predicted: 3 },
      ],
      skipped: [],
      coverage: {
        savings_reporting_total: 12.5,
        fit: { slope: 2, r2: 0.9 },
        provenance: "inline_series",
        site_performance_claim: false,
      },
    });

    render(<MvChangePointPanel />);

    await waitFor(() => {
      expect(screen.getByTestId("mv-savings").textContent).toContain("12.5");
    });
    const body = vi.mocked(postMvChangePoint).mock.calls[0]?.[0] as {
      building_id?: string;
      series?: { rows?: unknown[] };
    };
    expect(body.building_id).toBeUndefined();
    expect(body.series?.rows?.length).toBeGreaterThan(0);
    expect(screen.queryByTestId("mv-error")).toBeNull();
  });

  it("shows the handler error instead of a seeded result", async () => {
    vi.mocked(postMvChangePoint).mockRejectedValue(
      new Error("building_id is required"),
    );

    render(<MvChangePointPanel />);

    expect((await screen.findByTestId("mv-error")).textContent).toContain(
      "building_id is required",
    );
    expect(screen.getByTestId("mv-savings").textContent).toContain("—");
  });
});
