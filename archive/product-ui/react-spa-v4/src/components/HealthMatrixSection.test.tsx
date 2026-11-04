import { useRef } from "react";
import { describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { assignDataTableRowKeys, DataTable } from "./widgets/DataTable";
import {
  HealthMatrixSection,
  healthRowClass,
  healthRowClassBroken3Only,
  healthRowClassFullyBroken,
  tri,
} from "./HealthMatrixSection";
import type { AnalyticsEnvelope } from "../api/analyticsApi";
import {
  noteOverviewRuleCompletion,
  resetOverviewQueryPolicyForTests,
} from "../session/overviewQueryPolicy";

function emptyEnvelope(): AnalyticsEnvelope {
  return {
    schema_version: "sensor_fault_matrix_v1",
    query_version: "sensor-faults-v1",
    generated_at: "2026-08-20T00:00:00Z",
    engine: "datafusion",
    warnings: [],
    rows: [],
    equipment: [],
    points: [],
    skipped: [],
  };
}

describe("health matrix tint", () => {
  it("maps score to broken-N classes and skips unknown", () => {
    expect(healthRowClass("1/3")).toBe("health-row--broken-1");
    expect(healthRowClass("2/3")).toBe("health-row--broken-2");
    expect(healthRowClass("3/3")).toBe("health-row--broken-3");
    expect(healthRowClass("0/3")).toBeUndefined();
    expect(healthRowClass("?/3")).toBeUndefined();
    expect(tri(null)).toBe("unknown");
    expect(tri(null, { pending: true })).toBe("—");
    expect(tri(true)).toBe("true");
  });

  it("overview matrix highlights fully faulted arbitrary-width rows", () => {
    expect(healthRowClassFullyBroken("3/3")).toBe("health-row--broken-3");
    expect(healthRowClassFullyBroken("5/5")).toBe("health-row--broken-3");
    expect(healthRowClassFullyBroken("7/7")).toBe("health-row--broken-3");
    expect(healthRowClassFullyBroken("4/5")).toBeUndefined();
    expect(healthRowClassFullyBroken("?/7")).toBeUndefined();
    expect(healthRowClassBroken3Only("3/3")).toBe("health-row--broken-3");
    render(
      <DataTable
        id="h3"
        label="Health"
        testId="health-table-3only"
        columns={[
          { key: "equipment_id", header: "equip" },
          { key: "sat_dev", header: "flag" },
        ]}
        rows={[
          { score_label: "4/5", equipment_id: "AHU_2", sat_dev: "true" },
          { score_label: "5/5", equipment_id: "AHU_3", sat_dev: "true" },
        ]}
        rowClassName={(row) => healthRowClassFullyBroken(row.score_label)}
      />,
    );
    const rows = screen.getByTestId("health-table-3only").querySelectorAll("tbody tr");
    expect(rows[0].className).not.toContain("health-row--broken");
    expect(rows[0].getAttribute("data-broken")).toBeNull();
    expect(rows[1].className).toContain("health-row--broken-3");
    expect(rows[1].getAttribute("data-broken")).toBe("3");
  });

  it("tints DataTable rows via data-broken", () => {
    render(
      <DataTable
        id="h"
        label="Health"
        testId="health-table"
        columns={[
          { key: "score_label", header: "Score" },
          { key: "equipment_id", header: "Equipment" },
        ]}
        rows={[
          { score_label: "0/3", equipment_id: "AHU_0" },
          { score_label: "1/3", equipment_id: "AHU_1" },
          { score_label: "3/3", equipment_id: "AHU_3" },
          { score_label: "?/3", equipment_id: "AHU_q" },
        ]}
        rowClassName={(row) => healthRowClass(row.score_label)}
      />,
    );
    const rows = screen.getByTestId("health-table").querySelectorAll("tbody tr");
    expect(rows[0].getAttribute("data-broken")).toBeNull();
    expect(rows[1].getAttribute("data-broken")).toBe("1");
    expect(rows[1].className).toContain("health-row--broken-1");
    expect(rows[2].getAttribute("data-broken")).toBe("3");
    expect(rows[3].getAttribute("data-broken")).toBeNull();
  });

  it("keeps the clean sensor table shell visible", async () => {
    render(
      <HealthMatrixSection
        family="sensor"
        title="Sensor faults"
        caption="Sensor validation faults."
        buildingId="B1"
        refreshToken={0}
        fetchHealth={async () => emptyEnvelope()}
        flagColumns={[{ key: "flatline", ruleId: "SV-FLATLINE" }]}
        emptyMessage="No sensor faults in window"
        renderEmptyTable
      />,
    );

    expect(await screen.findByText("No sensor faults in window")).toBeTruthy();
    expect(screen.getByTestId("sensor-health-table")).toBeTruthy();
    expect(screen.getByText("SV-FLATLINE h")).toBeTruthy();
    const header = screen.getByText("SV-FLATLINE h").closest("th");
    expect(header?.getAttribute("title")).toBe("SV-FLATLINE fault_h");
  });

  it("recomputes only after the refresh token changes for the same building", async () => {
    const fetchHealth = vi.fn(async () => emptyEnvelope());
    const props = {
      family: "sensor",
      title: "Sensor faults",
      flagColumns: [{ key: "flatline", ruleId: "SV-FLATLINE" }],
      fetchHealth,
    };
    const view = render(
      <HealthMatrixSection {...props} buildingId="site-a" refreshToken={0} />,
    );
    await waitFor(() => {
      expect(fetchHealth).toHaveBeenCalledWith(
        "site-a",
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      );
    });
    expect(fetchHealth.mock.calls[0]?.[1]?.refresh).toBeUndefined();
    view.rerender(
      <HealthMatrixSection {...props} buildingId="site-a" refreshToken={1} />,
    );
    await waitFor(() => {
      expect(fetchHealth).toHaveBeenLastCalledWith(
        "site-a",
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      );
    });
    expect(fetchHealth.mock.calls.at(-1)?.[1]?.refresh).toBeUndefined();
    view.rerender(
      <HealthMatrixSection {...props} buildingId="site-b" refreshToken={1} />,
    );
    await waitFor(() => {
      expect(fetchHealth).toHaveBeenLastCalledWith(
        "site-b",
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      );
    });
    const last = fetchHealth.mock.calls.at(-1)?.[1];
    expect(last?.refresh).toBeUndefined();
  });

  it("recomputes only the query that depends on the finished rule", async () => {
    resetOverviewQueryPolicyForTests();
    const fetchHealth = vi.fn(async () => emptyEnvelope());
    const props = {
      family: "sensor",
      title: "Sensor faults",
      queryId: "sensor-faults",
      flagColumns: [{ key: "flatline", ruleId: "SV-FLATLINE" }],
      fetchHealth,
    };
    render(<HealthMatrixSection {...props} buildingId="site-a" refreshToken={0} />);
    await waitFor(() => {
      expect(fetchHealth).toHaveBeenCalledTimes(1);
    });
    act(() => {
      noteOverviewRuleCompletion("site-a", { mode: "single", rule_id: "CHW-1" });
    });
    expect(fetchHealth).toHaveBeenCalledTimes(1);
    act(() => {
      noteOverviewRuleCompletion("site-a", { mode: "single", rule_id: "SV-FLATLINE" });
    });
    await waitFor(() => {
      expect(fetchHealth).toHaveBeenLastCalledWith(
        "site-a",
        expect.objectContaining({ refresh: true }),
      );
    });
    expect(fetchHealth).toHaveBeenCalledTimes(2);
  });
});

function diagnosticEnvelope(
  site: string,
  queryId: string,
  rows: Record<string, unknown>[],
): AnalyticsEnvelope {
  return {
    schema_version: "diagnostic_matrix_v1",
    query_version: "diagnostic-matrix-v1",
    generated_at: "2026-10-22T00:00:00Z",
    engine: "timescale-sql",
    warnings: [],
    rows,
    equipment: [],
    points: [],
    skipped: [],
    site_id: site,
    building_id: site,
    query_id: queryId,
  };
}

function diagnosticRow(
  site: string,
  equipment: string,
  role: string,
  flag: string,
  kind: "fault" | "hunt",
): Record<string, unknown> {
  return {
    row_key: `${site}\u001f${equipment}\u001f${role}`,
    site_id: site,
    building_id: site,
    equipment_id: equipment,
    role,
    flag,
    flag_kind: kind,
    ...(kind === "fault" ? { fault_flag: flag } : { hunt_flag: flag }),
    n: 24,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function MountToken({ token }: { token: string }) {
  const first = useRef(token);
  return <span data-testid="mount-token">{first.current}</span>;
}

describe("diagnostic matrix rows", () => {
  const sensorColumns = [
    { key: "flatline", ruleId: "SV-FLATLINE" },
    { key: "range", ruleId: "SV-RANGE" },
  ];

  it("shows the proxy flag and role instead of unknown FDD columns", async () => {
    render(
      <HealthMatrixSection
        family="sensor"
        title="Sensor faults"
        buildingId="site-a"
        refreshToken={0}
        fetchHealth={async () =>
          diagnosticEnvelope("site-a", "sensor-faults", [
            diagnosticRow("site-a", "flat_unit", "sat", "FLATLINE", "fault"),
            diagnosticRow("site-a", "flat_unit", "zone_t", "OK", "fault"),
          ])
        }
        flagColumns={sensorColumns}
      />,
    );
    expect(await screen.findByText("FLATLINE")).toBeTruthy();
    expect(screen.getByText("sat")).toBeTruthy();
    expect(screen.getByText("zone_t")).toBeTruthy();
    expect(screen.getByText("OK")).toBeTruthy();
    expect(screen.queryByText("unknown")).toBeNull();
    expect(screen.queryByText("SV-FLATLINE")).toBeNull();
    const body = screen
      .getByTestId("sensor-health-table")
      .querySelectorAll("tbody tr");
    expect(body).toHaveLength(2);
    const keys = [...body].map((row) => row.getAttribute("data-row-key"));
    expect(keys).toEqual([
      "site-a\u001fflat_unit\u001fsat",
      "site-a\u001fflat_unit\u001fzone_t",
    ]);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("keeps the hunt flag on its role", async () => {
    render(
      <HealthMatrixSection
        family="pid"
        title="PID Hunting"
        buildingId="site-a"
        refreshToken={0}
        fetchHealth={async () =>
          diagnosticEnvelope("site-a", "pid-hunting", [
            diagnosticRow("site-a", "hunt_unit", "zone_t", "HUNT_PROXY", "hunt"),
            diagnosticRow("site-a", "hunt_unit", "sat", "OK", "hunt"),
          ])
        }
        flagColumns={[
          { key: "operating_state_hunt", ruleId: "FC4" },
          { key: "control_output_hunt", ruleId: "PID-HUNT-1" },
        ]}
      />,
    );
    expect(await screen.findByText("HUNT_PROXY")).toBeTruthy();
    expect(screen.getByText("hunt")).toBeTruthy();
    expect(screen.queryByText("FC4")).toBeNull();
    expect(screen.queryByText("unknown")).toBeNull();
  });

  it("collapses a repeated site equipment role and does not warn on duplicate keys", async () => {
    const errors: unknown[][] = [];
    const spy = vi.spyOn(console, "error").mockImplementation((...args) => {
      errors.push(args);
    });
    render(
      <HealthMatrixSection
        family="sensor"
        title="Sensor faults"
        buildingId="site-a"
        refreshToken={0}
        fetchHealth={async () =>
          diagnosticEnvelope("site-a", "sensor-faults", [
            diagnosticRow("site-a", "flat_unit", "sat", "OK", "fault"),
            diagnosticRow("site-a", "flat_unit", "sat", "FLATLINE", "fault"),
            diagnosticRow("site-a", "flat_unit", "zone_t", "OK", "fault"),
          ])
        }
        flagColumns={sensorColumns}
      />,
    );
    expect(await screen.findByText("FLATLINE")).toBeTruthy();
    const body = screen
      .getByTestId("sensor-health-table")
      .querySelectorAll("tbody tr");
    expect(body).toHaveLength(2);
    const keys = [...body].map((row) => row.getAttribute("data-row-key"));
    expect(new Set(keys).size).toBe(2);
    const warned = errors.some((args) =>
      args.some((part) => String(part).includes("same key")),
    );
    expect(warned).toBe(false);
    spy.mockRestore();
  });

  it("ignores a late response from the previous site", async () => {
    const siteA = deferred<AnalyticsEnvelope>();
    const siteB = deferred<AnalyticsEnvelope>();
    let signalA: AbortSignal | undefined;
    const fetchHealth = vi.fn((id: string, opts?: { signal?: AbortSignal }) => {
      if (id === "site-a") {
        signalA = opts?.signal;
        return siteA.promise;
      }
      return siteB.promise;
    });
    const props = {
      family: "sensor",
      title: "Sensor faults",
      flagColumns: sensorColumns,
      fetchHealth,
    };
    const view = render(
      <HealthMatrixSection {...props} buildingId="site-a" refreshToken={0} />,
    );
    await waitFor(() => {
      expect(signalA).toBeInstanceOf(AbortSignal);
    });
    view.rerender(
      <HealthMatrixSection {...props} buildingId="site-b" refreshToken={0} />,
    );
    expect(signalA?.aborted).toBe(true);
    siteA.resolve(
      diagnosticEnvelope("site-a", "sensor-faults", [
        diagnosticRow("site-a", "unit_from_a", "sat", "FLATLINE", "fault"),
      ]),
    );
    siteB.resolve(
      diagnosticEnvelope("site-b", "sensor-faults", [
        diagnosticRow("site-b", "unit_from_b", "zone_t", "OK", "fault"),
      ]),
    );
    expect(await screen.findByText("unit_from_b")).toBeTruthy();
    expect(screen.queryByText("unit_from_a")).toBeNull();
    const keys = [
      ...screen.getByTestId("sensor-health-table").querySelectorAll("tbody tr"),
    ].map((row) => row.getAttribute("data-row-key"));
    expect(keys).toEqual(["site-b\u001funit_from_b\u001fzone_t"]);
  });
});

describe("DataTable row keys", () => {
  it("remounts when the identity changes even if the displayed cells match", () => {
    const columns = [
      { key: "equipment_id", header: "equip" },
      { key: "role", header: "role" },
      { key: "flag", header: "flag" },
    ];
    const view = render(
      <DataTable
        id="swap"
        label="Health"
        testId="swap-table"
        columns={columns}
        rows={[
          {
            row_key: "site-a\u001fAHU\u001fsat",
            equipment_id: "AHU",
            role: "sat",
            flag: <MountToken token="site-a" />,
          },
        ]}
      />,
    );
    expect(screen.getByTestId("mount-token").textContent).toBe("site-a");
    view.rerender(
      <DataTable
        id="swap"
        label="Health"
        testId="swap-table"
        columns={columns}
        rows={[
          {
            row_key: "site-b\u001fAHU\u001fsat",
            equipment_id: "AHU",
            role: "sat",
            flag: <MountToken token="site-b" />,
          },
        ]}
      />,
    );
    expect(screen.getByTestId("mount-token").textContent).toBe("site-b");
  });

  it("assigns distinct keys when displayed cells and row_key collide", () => {
    const rows = [
      { row_key: "same", equipment_id: "AHU", role: "sat", flag: "OK" },
      { row_key: "same", equipment_id: "AHU", role: "sat", flag: "OK" },
    ];
    const keys = assignDataTableRowKeys(rows);
    expect(keys[0]).not.toBe(keys[1]);
    const errors: unknown[][] = [];
    const spy = vi.spyOn(console, "error").mockImplementation((...args) => {
      errors.push(args);
    });
    render(
      <DataTable
        id="dup"
        label="Health"
        testId="dup-table"
        columns={[
          { key: "equipment_id", header: "equip" },
          { key: "role", header: "role" },
          { key: "flag", header: "flag" },
        ]}
        rows={rows}
      />,
    );
    const body = screen.getByTestId("dup-table").querySelectorAll("tbody tr");
    expect(body).toHaveLength(2);
    const domKeys = [...body].map((row) => row.getAttribute("data-row-key"));
    expect(new Set(domKeys).size).toBe(2);
    expect(
      errors.some((args) => args.some((part) => String(part).includes("same key"))),
    ).toBe(false);
    spy.mockRestore();
  });

  it("keeps no-equipment, unsupported, no-history, and error distinct", async () => {
    const base = emptyEnvelope();
    const props = {
      family: "vav",
      title: "VAV zone health",
      buildingId: "B1",
      refreshToken: 0,
      flagColumns: [{ key: "poor_zone_performance", ruleId: "ZONE-COMFORT" }],
      renderEmptyTable: true,
    };
    const view = render(
      <HealthMatrixSection
        {...props}
        fetchHealth={async () => ({
          ...base,
          coverage: { availability: "no_equipment", message: "No VAV equipment in this data model." },
        })}
      />,
    );
    expect(await screen.findByTestId("vav-health-empty")).toBeTruthy();
    expect(screen.queryByTestId("vav-health-error")).toBeNull();
    expect(screen.queryByTestId("vav-health-unsupported")).toBeNull();
    expect(screen.queryByTestId("vav-health-no-history")).toBeNull();
    expect(screen.getByTestId("vav-health-table")).toBeTruthy();

    view.rerender(
      <HealthMatrixSection
        {...props}
        refreshToken={1}
        fetchHealth={async () => ({
          ...base,
          coverage: {
            availability: "unsupported",
            message: "VAV equipment is present, but no zone temperature role is mapped.",
          },
        })}
      />,
    );
    expect(await screen.findByTestId("vav-health-unsupported")).toBeTruthy();
    expect(screen.queryByTestId("vav-health-empty")).toBeNull();
    expect(screen.queryByTestId("vav-health-table")).toBeNull();
    expect(screen.queryByText(/No VAV equipment/)).toBeNull();

    view.rerender(
      <HealthMatrixSection
        {...props}
        refreshToken={2}
        fetchHealth={async () => ({
          ...base,
          coverage: {
            availability: "no_history",
            message: "VAV zone temperature is mapped, but this window has no samples.",
          },
        })}
      />,
    );
    expect(await screen.findByTestId("vav-health-no-history")).toBeTruthy();
    expect(screen.queryByTestId("vav-health-empty")).toBeNull();
    expect(screen.queryByText(/No VAV equipment/)).toBeNull();

    view.rerender(
      <HealthMatrixSection
        {...props}
        refreshToken={3}
        fetchHealth={async () => ({
          ...base,
          coverage: { availability: "error", message: "vav-health query failed" },
        })}
      />,
    );
    expect(await screen.findByTestId("vav-health-error")).toBeTruthy();
    expect(screen.queryByTestId("vav-health-empty")).toBeNull();
    expect(screen.queryByTestId("vav-health-table")).toBeNull();
    expect(screen.queryByText(/No VAV equipment/)).toBeNull();
  });
});
