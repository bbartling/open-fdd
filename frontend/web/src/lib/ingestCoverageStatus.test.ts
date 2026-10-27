import { describe, expect, it } from "vitest";
import {
  coverageStateLabel,
  coverageStateTone,
  coverageStatusFromFetch,
  pointsText,
} from "./ingestCoverageStatus";

const provider = (status: Record<string, unknown>, extra: Record<string, unknown> = {}) => ({
  tenant_id: "lab",
  schedule: { mode: "daily", timezone: "America/Chicago" },
  planned_through: "2026-10-20T05:00:00Z",
  next_run: "2026-10-21T05:05:00Z",
  schedule_error: null,
  gap_scan_truncated: false,
  status: {
    provider_instance_id: "nf:nf-site-a",
    approved_points: 3,
    withheld_points: 1,
    discovered_points: 4,
    verified_through: null,
    oldest_gap: null,
    state: "behind",
    ...status,
  },
  ...extra,
});

describe("ingest coverage status", () => {
  it("reads schedule, horizon, points, and the oldest gap", () => {
    const view = coverageStatusFromFetch({
      http: "ok",
      body: {
        state: "gap",
        providers: [
          provider({
            state: "gap",
            verified_through: "2026-10-19T05:00:00Z",
            oldest_gap: {
              device_id: "AHU_1",
              start: "2026-10-19T05:00:00Z",
              end: "2026-10-20T05:00:00Z",
              state: "partial",
              code: "fetch_incomplete",
            },
          }),
        ],
      },
    });
    expect(view.status).toBe("ready");
    if (view.status !== "ready") return;
    const [row] = view.rows;
    expect(row.mode).toBe("daily");
    expect(row.timezone).toBe("America/Chicago");
    expect(row.nextRun).toBe("2026-10-21T05:05:00Z");
    expect(row.verifiedThrough).toBe("2026-10-19T05:00:00Z");
    expect(pointsText(row)).toBe("3 of 4 (1 withheld)");
    expect(row.oldestGap).toBe(
      "AHU_1 · 2026-10-19T05:00:00Z → 2026-10-20T05:00:00Z · partial · fetch_incomplete",
    );
    expect(coverageStateTone(row.state)).toBe("bad");
  });

  it("never shows missing counts as zero or an unknown state as verified", () => {
    const view = coverageStatusFromFetch({
      http: "ok",
      body: {
        state: "mystery",
        providers: [provider({ state: "mystery", approved_points: undefined, withheld_points: undefined })],
      },
    });
    if (view.status !== "ready") throw new Error("expected ready");
    expect(pointsText(view.rows[0])).toBe("— of 4");
    expect(coverageStateLabel("mystery")).toBe("Unrecognized state (mystery)");
    expect(coverageStateTone("mystery")).toBe("neutral");
    expect(coverageStateLabel("")).toBe("Unrecognized state (missing)");
    expect(coverageStateLabel("not_assessed")).toBe("Not assessed");
    expect(coverageStateTone("not_assessed")).toBe("neutral");
  });

  it("surfaces site not assessed reason text", () => {
    const view = coverageStatusFromFetch({
      http: "ok",
      body: {
        state: "not_assessed",
        state_reason: "cadence_not_bound",
        providers: [provider({ state: "not_assessed", state_reason: "cadence_not_bound" })],
      },
    });
    if (view.status !== "ready") throw new Error("expected ready");
    expect(view.stateReason).toBe("cadence_not_bound");
    expect(view.rows[0].stateReason).toBe("cadence_not_bound");
  });

  it("treats a body without providers as an error and a 404 as unavailable", () => {
    expect(coverageStatusFromFetch({ http: "ok", body: { ok: true } }).status).toBe("error");
    expect(coverageStatusFromFetch({ http: "missing" }).status).toBe("unavailable");
    expect(coverageStatusFromFetch({ http: "error", message: "boom" })).toEqual({
      status: "error",
      message: "boom",
    });
  });
});
