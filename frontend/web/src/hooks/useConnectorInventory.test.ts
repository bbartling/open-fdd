import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import {
  type ConnectorInventoryResponse,
  type InventoryRecord,
  type InventoryScope,
} from "../api/inventoryApi";
import { useConnectorInventory } from "./useConnectorInventory";

const { fetchPage } = vi.hoisted(() => ({ fetchPage: vi.fn() }));

vi.mock("../api/inventoryApi", async () => {
  const actual = await vi.importActual<typeof import("../api/inventoryApi")>("../api/inventoryApi");
  return { ...actual, fetchConnectorInventoryPage: fetchPage };
});

const scopeA: InventoryScope = { tenant_id: "tenant-a", building_id: "building-a", edge_id: "edge-a" };
const scopeB: InventoryScope = { tenant_id: "tenant-b", building_id: "building-b", edge_id: "edge-b" };

const device: InventoryRecord = {
  kind: "device",
  device_id: "opaque-device",
  protocol: "bacnet",
  display_name: "Device",
  availability: "configured",
  commandability: "unknown",
  actions: ["metadata_read"],
};

const group: InventoryRecord = {
  kind: "group",
  group_id: "opaque-group",
  device_id: "opaque-device",
  protocol: "bacnet",
  display_name: "Analog values",
  availability: "configured",
  commandability: "unknown",
  actions: ["metadata_read"],
};

const point: InventoryRecord = {
  kind: "point",
  point_id: "opaque-point",
  device_id: "opaque-device",
  group_id: "opaque-group",
  protocol: "bacnet",
  display_name: "Supply temperature",
  units: "degF",
  availability: "configured",
  commandability: "unknown",
  actions: ["point_read"],
  reference: {
    kind: "bacnet",
    device_instance: 7,
    object_type: "analog-value",
    object_instance: 1,
    property_id: "present-value",
  },
};

function page(scope: InventoryScope, records: InventoryRecord[], overrides: Partial<ConnectorInventoryResponse> = {}): ConnectorInventoryResponse {
  return {
    schema: "openfdd.connector.inventory.v1",
    request_id: "request",
    scope,
    protocols: [...new Set(records.map((record) => record.protocol))],
    revision: "revision-1",
    captured_at: "2026-10-01T00:00:00Z",
    provenance: "trusted_configuration",
    records,
    next_cursor: null,
    ...overrides,
  };
}

describe("useConnectorInventory", () => {
  beforeEach(() => fetchPage.mockReset());
  afterEach(() => vi.restoreAllMocks());

  it("loads opaque-cursor pages and attaches cross-page parents after accumulation", async () => {
    fetchPage
      .mockResolvedValueOnce(page(scopeA, [point], { next_cursor: "opaque-cursor-1" }))
      .mockResolvedValueOnce(page(scopeA, [device, group]));
    const hook = renderHook(() => useConnectorInventory({ scope: scopeA, protocols: ["bacnet"], pageSize: 2 }));

    await waitFor(() => expect(hook.result.current.status).toBe("ready"));
    expect(hook.result.current.records.map((record) => record.kind)).toEqual(["point", "device", "group"]);
    expect(fetchPage).toHaveBeenCalledTimes(2);
    expect(fetchPage.mock.calls[1][0]).toMatchObject({ cursor: "opaque-cursor-1", scope: scopeA });
  });

  it("keeps a partial page and reports revision changes or repeated cursors", async () => {
    fetchPage
      .mockResolvedValueOnce(page(scopeA, [device], { next_cursor: "cursor-1" }))
      .mockResolvedValueOnce(page(scopeA, [group], { revision: "revision-2" }));
    const revisionHook = renderHook(() => useConnectorInventory({ scope: scopeA, protocols: ["bacnet"] }));
    await waitFor(() => expect(revisionHook.result.current.status).toBe("partial"));
    expect(revisionHook.result.current.records).toHaveLength(1);
    expect(revisionHook.result.current.error?.message).toContain("revision changed");

    fetchPage
      .mockResolvedValueOnce(page(scopeA, [device], { next_cursor: "cursor-1" }))
      .mockResolvedValueOnce(page(scopeA, [group], { next_cursor: "cursor-1" }));
    act(() => revisionHook.result.current.refresh());
    await waitFor(() => expect(revisionHook.result.current.error?.message).toContain("repeated a continuation cursor"));
    expect(revisionHook.result.current.partial).toBe(true);
  });

  it("ignores a cancelled scope's late page and resets records on scope change", async () => {
    let resolveA: ((value: ConnectorInventoryResponse) => void) | undefined;
    fetchPage.mockImplementationOnce(() => new Promise((resolve) => { resolveA = resolve; }));
    fetchPage.mockResolvedValueOnce(page(scopeB, [group]));
    const hook = renderHook(
      ({ scope }: { scope: InventoryScope }) => useConnectorInventory({ scope, protocols: ["bacnet"] }),
      { initialProps: { scope: scopeA } },
    );
    hook.rerender({ scope: scopeB });
    await waitFor(() => expect(hook.result.current.status).toBe("ready"));
    expect(hook.result.current.records).toEqual([group]);
    await act(async () => {
      resolveA?.(page(scopeA, [device]));
      await Promise.resolve();
    });
    expect(hook.result.current.records).toEqual([group]);
  });

  it("does not issue a request until the full explicit scope exists", async () => {
    const hook = renderHook(() => useConnectorInventory({ scope: null, protocols: ["bacnet"] }));
    await Promise.resolve();
    expect(fetchPage).not.toHaveBeenCalled();
    expect(hook.result.current.status).toBe("idle");
  });

  it("retains authenticated 401/403 transport errors without broadening the scope", async () => {
    const forbidden = Object.assign(new Error("forbidden"), { status: 403 });
    fetchPage.mockRejectedValueOnce(forbidden);
    const hook = renderHook(() => useConnectorInventory({ scope: scopeA, protocols: ["haystack"] }));
    await waitFor(() => expect(hook.result.current.status).toBe("error"));
    expect(hook.result.current.error).toBe(forbidden);
    expect(hook.result.current.records).toEqual([]);
  });
});
