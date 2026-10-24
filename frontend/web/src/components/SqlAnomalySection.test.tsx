import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import fixture from "../fixtures/sqlAnomalyEventV1.json";
import type { AnalyticsEnvelope } from "../api/analyticsApi";
import { SqlAnomalySection } from "./SqlAnomalySection";
import type { AnomalyEnvelopeInput } from "./sqlAnomaly";

const { postSqlAnomaly } = vi.hoisted(() => ({
  postSqlAnomaly: vi.fn(),
}));

vi.mock("../api/analyticsApi", () => ({
  postSqlAnomaly,
}));

interface FixtureCase extends AnomalyEnvelopeInput {
  query_version: string;
  warnings: string[];
  rows: Record<string, unknown>[];
  coverage: Record<string, unknown>;
}

const cases = fixture.cases as Record<string, FixtureCase>;

function envelope(name: string): AnalyticsEnvelope {
  const item = cases[name];
  return {
    schema_version: "",
    query_version: item.query_version,
    generated_at: "",
    engine: "timescale-sql",
    warnings: item.warnings,
    rows: item.rows,
    equipment: [],
    points: [],
    skipped: [],
    coverage: item.coverage,
  };
}

function emptyEnvelope(): AnalyticsEnvelope {
  return {
    schema_version: "",
    query_version: "sql-anomaly-event-v1",
    generated_at: "",
    engine: "timescale-sql",
    warnings: [],
    rows: [],
    equipment: [],
    points: [],
    skipped: [],
  };
}

describe("SqlAnomalySection", () => {
  it("renders every flagged timestamp, both series, and the interior edge", async () => {
    postSqlAnomaly.mockResolvedValue(envelope("multi_event"));
    render(<SqlAnomalySection buildingId="SITE" refreshToken={0} />);
    const table = await screen.findByTestId("overview-sql-anomaly-table");
    const body = table.querySelectorAll("tbody tr");
    expect(body.length).toBe(envelope("multi_event").rows.length);
    expect(table.textContent).toContain("false");
    expect(table.textContent).toContain("80");
    expect(table.textContent).not.toContain("—");
    expect(table.textContent).not.toContain("anomaly h");
    const keys = [...table.querySelectorAll("tbody tr")].map((row) =>
      row.getAttribute("data-row-key"),
    );
    expect(new Set(keys).size).toBe(keys.length);
    expect(keys.every((key) => key?.includes("|"))).toBe(true);
  });

  it("shows rising-edge coverage when interior flags are omitted", async () => {
    postSqlAnomaly.mockResolvedValue(envelope("transition_edges"));
    render(<SqlAnomalySection buildingId="SITE" refreshToken={0} />);
    const note = await screen.findByTestId("overview-sql-anomaly-edges");
    const flagged = envelope("transition_edges").coverage?.n_flagged;
    expect(note.textContent).toContain("Showing rising edges.");
    expect(note.textContent).toContain(String(flagged));
    const table = screen.getByTestId("overview-sql-anomaly-table");
    expect(
      [...table.querySelectorAll("tbody td")].some((cell) => cell.textContent === "false"),
    ).toBe(false);
  });

  it("explains quiet, short, missing, and constant history", async () => {
    const notes: Array<[string, string]> = [
      ["no_event", "No anomaly events at this threshold."],
      ["short_history", "History is shorter than the window, so no anomaly events were scored."],
      ["missing_values", "Screened points have no numeric history in this window."],
      ["constant_history", "History has no variance, so no anomaly events were scored."],
    ];
    for (const [name, text] of notes) {
      postSqlAnomaly.mockResolvedValue(envelope(name));
      const view = render(<SqlAnomalySection buildingId="SITE" refreshToken={0} />);
      expect((await screen.findByTestId("overview-sql-anomaly-empty")).textContent).toContain(text);
      view.unmount();
    }
  });

  it("prints the offset spike in UTC with its exact fractional value", async () => {
    postSqlAnomaly.mockResolvedValue(envelope("timezone_precision"));
    render(<SqlAnomalySection buildingId="SITE" refreshToken={0} />);
    const table = await screen.findByTestId("overview-sql-anomaly-table");
    expect(table.textContent).toContain("80.125");
    expect(table.textContent).toContain("2026-06-16 00:15:00Z");
    expect(table.textContent).not.toContain("-04");
  });

  it("rejects a summary payload instead of rendering dash columns", async () => {
    postSqlAnomaly.mockResolvedValue({
      schema_version: "",
      query_version: "sql-anomaly-v1",
      generated_at: "",
      engine: "",
      warnings: [],
      rows: [
        {
          equipment_id: "X",
          role: "sat",
          score: 4,
          anomaly_hours: 2,
          anomaly_events: 1,
          last_at: "2026-06-01T00:00:00Z",
          threshold: 3,
          method: "zscore",
        },
      ],
      equipment: [],
      points: [],
      skipped: [],
    });
    render(<SqlAnomalySection buildingId="SITE" refreshToken={0} />);
    expect((await screen.findByTestId("overview-sql-anomaly-err")).textContent).toContain(
      "Anomaly response does not match the event contract.",
    );
    expect(screen.queryByText("anomaly h")).toBeNull();
    expect(screen.queryByTestId("overview-sql-anomaly-table")).toBeNull();
  });

  it("posts window, threshold, and rising-edge controls", async () => {
    postSqlAnomaly.mockResolvedValue(emptyEnvelope());
    render(<SqlAnomalySection buildingId="SITE" refreshToken={0} />);
    await waitFor(() => expect(postSqlAnomaly).toHaveBeenCalled());
    fireEvent.change(screen.getByTestId("overview-sql-anomaly-window"), {
      target: { value: "10" },
    });
    fireEvent.change(screen.getByTestId("overview-sql-anomaly-threshold"), {
      target: { value: "30" },
    });
    fireEvent.click(screen.getByTestId("overview-sql-anomaly-transitions"));
    await waitFor(() => {
      const last = postSqlAnomaly.mock.calls.at(-1);
      expect(last?.[0]).toEqual(
        expect.objectContaining({
          building_id: "SITE",
          query_version: "sql-anomaly-event-v1",
          series: {
            window_rows: 10,
            z_threshold: 30,
            method: "zscore",
            transition_events: true,
          },
        }),
      );
      expect(last?.[1]).toEqual(expect.objectContaining({ signal: expect.any(AbortSignal) }));
    });
  });
});
