import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { AdminCapacityStrip } from "./AdminCapacityStrip";

vi.mock("../api/hostStatsApi", () => ({
  formatBytes: (value: number | null | undefined) =>
    value == null ? "—" : `${value}`,
  getHostStats: vi.fn(async () => ({
    ok: true,
    memory: { source: "cgroup", used_bytes: 10, total_bytes: 100, percent_used: 10 },
    storage: { used_bytes: 20, total_bytes: 200, percent_used: 10 },
    data_management: { parquet: { estimated_bytes: 5, file_count: 2, small_file_count: 1 } },
  })),
  getHistorianCompactionStatus: vi.fn(async () => ({
    ok: true,
    engine: "timescale-sql",
    parquet_compaction: "not_applicable",
    note: "Product historian is Timescale",
  })),
  runHistorianCompaction: vi.fn(),
}));

describe("AdminCapacityStrip", () => {
  it("names Timescale as the historian and does not offer parquet compaction", async () => {
    render(<AdminCapacityStrip sizeGib={1} />);
    expect(await screen.findByTestId("admin-timescale-capacity")).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByTestId("admin-timescale-capacity").textContent).toMatch(/Timescale/);
    });
    expect(screen.getByTestId("admin-ingest-queue").textContent).toMatch(/Not reported/);
    expect(screen.getByTestId("admin-compact-disabled")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Compact analytics cache/i })).toBeNull();
    expect(screen.getByTestId("admin-capacity-strip").textContent).not.toMatch(/Historian Parquet/);
  });
});
