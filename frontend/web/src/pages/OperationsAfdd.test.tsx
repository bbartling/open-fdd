import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { OperationsPage } from "./OperationsPage";

const calls: Array<{ path: string; body?: string }> = [];

vi.mock("../api/client", () => ({
  apiFetch: vi.fn(async (path: string, init?: RequestInit) => {
    calls.push({ path, body: typeof init?.body === "string" ? init.body : undefined });
    if (path === "/api/afdd/scheduler/status") {
      return {
        ok: true,
        config: {
          mode: "continuous",
          interval_minutes: 1440,
          lookback_value: 1,
          lookback_unit: "days",
          schedule_kind: "wall_clock",
          wall_clock_hhmm: "05:00",
          wall_clock_timezone: "America/Chicago",
        },
        recent_cycles: [],
        operator_schedule_editable: true,
        next_due_at_utc: "2026-09-30T10:00:00.000Z",
        next_due_local: "2026-09-30T05:00:00-05:00",
        result_write: "lookback_window",
      };
    }
    if (path === "/api/afdd/scheduler/config" || path === "/api/afdd/scheduler/backfill") {
      return { ok: true };
    }
    if (path === "/api/mqtt/monitor") {
      return {
        connected: false,
        subscriptions: [],
        received_messages: 0,
        reconnects: 0,
        errors: 0,
        buffer_capacity: 0,
        recent_messages: [],
        recent_events: [],
        test_publish_enabled: false,
      };
    }
    return {};
  }),
  apiFetchBlob: vi.fn(),
}));

describe("Operations AFDD schedule", () => {
  beforeEach(() => {
    calls.length = 0;
  });

  it("shows the wall-clock due time and saves without update-all", async () => {
    render(
      <MemoryRouter initialEntries={["/operations?view=afdd"]}>
        <OperationsPage />
      </MemoryRouter>,
    );

    expect(await screen.findByDisplayValue("America/Chicago")).toBeTruthy();
    expect(screen.getByText(/Lookback window only/)).toBeTruthy();
    expect(screen.getByText(/local 2026-09-30T05:00:00-05:00/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /update all/i })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Save schedule" }));

    await waitFor(() => {
      const save = calls.find((call) => call.path === "/api/afdd/scheduler/config");
      expect(save?.body).toBeTruthy();
    });
    const save = calls.find((call) => call.path === "/api/afdd/scheduler/config");
    const payload = JSON.parse(save?.body ?? "{}") as Record<string, unknown>;
    expect(payload.schedule_kind).toBe("wall_clock");
    expect(payload.wall_clock_hhmm).toBe("05:00");
    expect(payload.wall_clock_timezone).toBe("America/Chicago");
    expect(payload.lookback_days).toBe(1);
    expect(payload).not.toHaveProperty("update_all");
  });
});
