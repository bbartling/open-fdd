import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  PRIORITY_SCAN_CONTRACT_V1,
  PriorityHistoryContractError,
  fetchPriorityHistoryPage,
} from "./priorityHistoryApi";

const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock("./client", () => ({ apiFetch }));
vi.mock("./requestId", () => ({ newRequestId: () => "request-1" }));

const scope = { tenant_id: "tenant-a", building_id: "building-a", edge_id: "edge-a" };

function slots() {
  return Array.from({ length: 16 }, (_, index) => ({
    priority_level: index + 1,
    state: index === 0 ? "value" : "null",
    type: index === 0 ? "real" : "null",
    ...(index === 0 ? { value: 72.5 } : {}),
  }));
}

function response(overrides: Record<string, unknown> = {}) {
  const target = { device_instance: 7, object_type: "analog-output", object_instance: 2 };
  return {
    schema: PRIORITY_SCAN_CONTRACT_V1,
    request_id: "request-1",
    scope,
    revision: "history-0000000000000001",
    captured_at: "2026-10-01T00:00:00Z",
    records: [{
      sequence: 1,
      target,
      label: "Supply command",
      snapshot: {
        ...target,
        slots: slots(),
        state: "supported",
        observed_at: "2026-10-01T00:00:00Z",
      },
      source: "scheduled_scan",
    }],
    next_cursor: null,
    scanner: {
      schema: PRIORITY_SCAN_CONTRACT_V1,
      scope,
      enabled: false,
      interval_secs: 3600,
      max_points_per_device: 100,
      catch_up: false,
      read_only: true,
      discovery_enabled: false,
      writes_enabled: false,
      last_started_at: null,
      last_completed_at: null,
      next_due_at: null,
      last_device_identity: null,
      last_error: null,
      records_retained: 1,
    },
    ...overrides,
  };
}

describe("priorityHistoryApi", () => {
  beforeEach(() => apiFetch.mockReset());

  it("posts an exact target-scoped history request and validates P1-P16", async () => {
    apiFetch.mockResolvedValue(response());
    const target = { device_instance: 7, object_type: "analog-output", object_instance: 2 };
    await expect(fetchPriorityHistoryPage({ scope, target, pageSize: 10 })).resolves.toMatchObject({
      records: [expect.objectContaining({ sequence: 1, label: "Supply command" })],
      scanner: expect.objectContaining({ enabled: false, interval_secs: 3600 }),
    });
    expect(apiFetch).toHaveBeenCalledWith("/api/connectors/edge-a/priority-history", expect.objectContaining({
      method: "POST",
      body: expect.stringContaining('"page_size":10'),
    }));
  });

  it("rejects a malformed snapshot and an unsafe scanner status", async () => {
    const malformed = response();
    (malformed.records[0] as { snapshot: { slots: unknown[] } }).snapshot.slots.pop();
    apiFetch.mockResolvedValueOnce(malformed);
    await expect(fetchPriorityHistoryPage({ scope })).rejects.toThrow(/P1-P16/);

    const unsafe = response({ scanner: { ...response().scanner, writes_enabled: true } });
    apiFetch.mockResolvedValueOnce(unsafe);
    await expect(fetchPriorityHistoryPage({ scope })).rejects.toBeInstanceOf(PriorityHistoryContractError);
  });

  it("rejects invalid page bounds before making a request", async () => {
    await expect(fetchPriorityHistoryPage({ scope, pageSize: 101 })).rejects.toThrow(/page size/);
    expect(apiFetch).not.toHaveBeenCalled();
  });
});
