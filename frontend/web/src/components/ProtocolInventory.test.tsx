import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { ProtocolInventory } from "./ProtocolInventory";
import type { ConnectorInventoryResponse, InventoryRecord } from "../api/inventoryApi";

const { apiFetch, fetchPage, fetchHistory } = vi.hoisted(() => ({
  apiFetch: vi.fn(),
  fetchPage: vi.fn(),
  fetchHistory: vi.fn(),
}));

vi.mock("../api/client", () => ({ apiFetch }));
vi.mock("../api/inventoryApi", async () => {
  const actual = await vi.importActual<typeof import("../api/inventoryApi")>("../api/inventoryApi");
  return { ...actual, fetchConnectorInventoryPage: fetchPage };
});
vi.mock("../api/authApi", () => ({ getStoredToken: vi.fn(() => "authenticated") }));
vi.mock("../api/tenantApi", () => ({ getStoredActiveTenant: vi.fn(() => null) }));
vi.mock("../api/priorityHistoryApi", async () => {
  const actual = await vi.importActual<typeof import("../api/priorityHistoryApi")>("../api/priorityHistoryApi");
  return { ...actual, fetchPriorityHistoryPage: fetchHistory };
});

const scope = { tenant_id: "tenant-a", building_id: "building-a", edge_id: "edge-a" };
const device: InventoryRecord = {
  kind: "device",
  device_id: "opaque-device",
  protocol: "bacnet",
  display_name: "Opaque device",
  availability: "configured",
  commandability: "unknown",
  actions: ["metadata_read"],
};
const group: InventoryRecord = {
  kind: "group",
  group_id: "opaque-group",
  device_id: "opaque-device",
  protocol: "bacnet",
  display_name: "Object group",
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
  availability: "unavailable",
  commandability: "unknown",
  actions: [],
  reference: {
    kind: "bacnet",
    device_instance: 7,
    object_type: "analog-value",
    object_instance: 1,
    property_id: "present-value",
  },
};
const secondPoint: InventoryRecord = {
  ...point,
  point_id: "opaque-point-2",
  display_name: "Return temperature",
  reference: {
    kind: "bacnet",
    device_instance: 7,
    object_type: "analog-value",
    object_instance: 2,
    property_id: "present-value",
  },
};

function page(records: InventoryRecord[]): ConnectorInventoryResponse {
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
  };
}

function historyPage() {
  const target = { device_instance: 7, object_type: "analog-value", object_instance: 1 };
  return {
    schema: "openfdd.connector.priority_scan.v1" as const,
    request_id: "request-1",
    scope,
    revision: "history-1",
    captured_at: "2026-10-01T00:00:00Z",
    records: [{
      sequence: 1,
      target,
      label: "Supply command",
      snapshot: {
        ...target,
        slots: Array.from({ length: 16 }, (_, index) => ({
          priority_level: index + 1,
          state: index === 0 ? "value" as const : "null" as const,
          type: index === 0 ? "real" : "null",
          ...(index === 0 ? { value: 71.5 } : {}),
        })),
        state: "supported" as const,
        observed_at: "2026-10-01T00:00:00Z",
      },
      source: "scheduled_scan" as const,
    }],
    next_cursor: null,
    scanner: {
      schema: "openfdd.connector.priority_scan.v1" as const,
      scope,
      enabled: false,
      interval_secs: 3600,
      max_points_per_device: 100,
      catch_up: false as const,
      read_only: true as const,
      discovery_enabled: false as const,
      writes_enabled: false as const,
      last_started_at: null,
      last_completed_at: null,
      next_due_at: null,
      last_device_identity: null,
      last_error: null,
      records_retained: 1,
    },
  };
}

function renderInventory(
  capabilityEdgeIds: readonly string[] = [],
  records: InventoryRecord[] = [device, group, point],
  priorityHistoryCapabilityEdgeIds: readonly string[] = [],
) {
  apiFetch.mockImplementation(async (path: string) => {
    if (path === "/api/tenants") {
      return {
        ok: true,
        active_tenant_id: "tenant-a",
        buildings_visible: ["building-a"],
        tenants: [{ id: "tenant-a", name: "Tenant A", building_ids: ["building-a"] }],
      };
    }
    if (path === "/api/edges") return { ok: true, edges: [{ edge_id: "edge-a", site_id: "building-a" }] };
    return {};
  });
  fetchPage.mockResolvedValue(page(records));
  return render(
    <MemoryRouter initialEntries={["/operations?site=building-a&edge=edge-a"]}>
      <ProtocolInventory
        protocol="bacnet"
        capabilityEdgeIds={capabilityEdgeIds}
        priorityHistoryCapabilityEdgeIds={priorityHistoryCapabilityEdgeIds}
      />
    </MemoryRouter>,
  );
}

describe("ProtocolInventory", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    fetchPage.mockReset();
    fetchHistory.mockReset();
    Object.assign(navigator, { clipboard: { writeText: vi.fn() } });
  });

  it("uses the selected authenticated scope and renders unavailable provenance honestly", async () => {
    renderInventory();
    await screen.findByTestId("inventory-treeitem-point:opaque-point");
    expect(screen.getByTestId("inventory-tree")).toBeTruthy();
    expect((screen.getByTestId("inventory-building") as HTMLSelectElement).value).toBe("building-a");
    expect((screen.getByTestId("inventory-edge") as HTMLSelectElement).value).toBe("edge-a");
    expect(fetchPage).toHaveBeenCalledWith(expect.objectContaining({ scope, protocols: ["bacnet"] }));
    fireEvent.click(screen.getByText("Supply temperature"));
    expect((await screen.findByTestId("inventory-details")).textContent).toContain("unavailable");
    expect(screen.getByTestId("inventory-details").textContent).toContain("trusted configuration");
    expect(screen.getByTestId("inventory-details").textContent).toContain("2026-10-01T00:00:00Z");
  });

  it("supports roving arrows, home/end, selection, and keyboard context escape", async () => {
    renderInventory();
    await screen.findByTestId("inventory-treeitem-point:opaque-point");
    await screen.findByTestId("inventory-treeitem-device:opaque-device");
    const deviceItem = screen.getByTestId("inventory-treeitem-device:opaque-device");
    deviceItem.focus();
    fireEvent.keyDown(deviceItem, { key: "ArrowLeft" });
    expect(deviceItem.getAttribute("aria-expanded")).toBe("false");
    fireEvent.keyDown(deviceItem, { key: "ArrowRight" });
    await waitFor(() => expect(deviceItem.getAttribute("aria-expanded")).toBe("true"));
    fireEvent.keyDown(deviceItem, { key: "ArrowRight" });
    const groupItem = screen.getByTestId("inventory-treeitem-group:opaque-group");
    expect(document.activeElement).toBe(groupItem);
    fireEvent.keyDown(groupItem, { key: "ArrowRight" });
    fireEvent.keyDown(groupItem, { key: "ArrowDown" });
    const pointItem = screen.getByTestId("inventory-treeitem-point:opaque-point");
    expect(document.activeElement).toBe(pointItem);
    fireEvent.keyDown(pointItem, { key: "Enter" });
    expect(screen.getByTestId("inventory-details").textContent).toContain("Supply temperature");
    fireEvent.keyDown(pointItem, { key: "Home" });
    expect(document.activeElement).toBe(deviceItem);
    fireEvent.keyDown(deviceItem, { key: "End" });
    expect(document.activeElement).toBe(pointItem);
    fireEvent.keyDown(pointItem, { key: "F10", shiftKey: true });
    const menu = await screen.findByTestId("inventory-context-menu");
    expect(menu.textContent).toContain("View details");
    fireEvent.keyDown(screen.getByRole("menuitem", { name: "View details" }), { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("inventory-context-menu")).toBeNull());
    expect(document.activeElement).toBe(pointItem);
  });

  it("limits pointer context actions to details, copy, and expansion", async () => {
    renderInventory();
    const groupItem = await screen.findByTestId("inventory-treeitem-group:opaque-group");
    fireEvent.contextMenu(groupItem);
    const menu = await screen.findByTestId("inventory-context-menu");
    expect(menu.textContent).toContain("Copy ID");
    expect(menu.textContent).not.toMatch(/read|write|discover|release/i);
    fireEvent.click(screen.getByRole("menuitem", { name: "Copy ID" }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("opaque-group");
  });

  it("performs one explicit advertised read and never reads during selection", async () => {
    renderInventory([], [device, group, { ...point, availability: "configured", actions: ["point_read"] }]);
    const pointItem = await screen.findByTestId("inventory-treeitem-point:opaque-point");
    fireEvent.click(pointItem);
    expect(apiFetch.mock.calls.some(([path]) => String(path).includes("/read"))).toBe(false);
    apiFetch.mockImplementation(async (path: string, options?: RequestInit) => {
      if (path === "/api/tenants") return {
        ok: true, active_tenant_id: "tenant-a", buildings_visible: ["building-a"],
        tenants: [{ id: "tenant-a", name: "Tenant A", building_ids: ["building-a"] }],
      };
      if (path === "/api/edges") return { ok: true, edges: [{ edge_id: "edge-a", site_id: "building-a" }] };
      if (path === "/api/connectors/edge-a/read") {
        const request = JSON.parse(String(options?.body));
        return {
          schema: "openfdd.connector.read.v1", request_id: request.request_id, scope, ok: true,
          capability_contract: "openfdd.connector.capabilities.v1", error: null,
          result: { kind: "point", device_instance: 7, object_type: "analog-value", object_instance: 1, property_id: "present-value", type: "real", value: 71.25, quality: "good", observed_at: "2026-10-01T01:00:00Z" },
        };
      }
      return {};
    });
    fireEvent.click(screen.getByRole("button", { name: "Read point" }));
    expect((await screen.findByTestId("inventory-read-point-result")).textContent).toContain("71.25");
    expect(apiFetch.mock.calls.filter(([path]) => String(path).includes("/read"))).toHaveLength(1);
  });

  it("gates each live-read button to the advertised action", async () => {
    renderInventory([], [device, group, { ...point, availability: "configured", actions: ["priority_array_read"] }]);
    const pointItem = await screen.findByTestId("inventory-treeitem-point:opaque-point");
    fireEvent.click(pointItem);
    expect(await screen.findByRole("button", { name: "Read priority array" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Read point" })).toBeNull();
  });

  it("loads durable priority history only after explicit user action", async () => {
    fetchHistory.mockResolvedValue(historyPage());
    renderInventory([], [device, group, { ...point, availability: "configured", actions: [] }], ["edge-a"]);
    const pointItem = await screen.findByTestId("inventory-treeitem-point:opaque-point");
    fireEvent.click(pointItem);
    const panel = await screen.findByTestId("inventory-priority-history");
    expect(fetchHistory).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Load history" }));
    await screen.findByTestId("inventory-priority-history-table");
    expect(fetchHistory).toHaveBeenCalledWith(expect.objectContaining({
      scope,
      target: { device_instance: 7, object_type: "analog-value", object_instance: 1 },
    }));
    expect(panel.textContent).toContain("P1");
    expect(panel.textContent).toContain("Supply command");
    expect(apiFetch.mock.calls.some(([path]) => String(path).includes("priority-history"))).toBe(false);
  });

  it("gates durable history on the connector capability, independently of point actions", async () => {
    fetchHistory.mockResolvedValue(historyPage());
    renderInventory([], [device, group, { ...point, availability: "configured", actions: [] }], ["edge-a"]);
    fireEvent.click(await screen.findByTestId("inventory-treeitem-point:opaque-point"));
    expect(await screen.findByTestId("inventory-priority-history")).toBeTruthy();
  });

  it("does not infer durable history capability from a point read action", async () => {
    renderInventory([], [device, group, { ...point, availability: "configured", actions: ["priority_array_read"] }]);
    fireEvent.click(await screen.findByTestId("inventory-treeitem-point:opaque-point"));
    expect(screen.queryByTestId("inventory-priority-history")).toBeNull();
  });

  it("submits one live read and blocks every other action while it is pending", async () => {
    let resolveRead: ((value: unknown) => void) | undefined;
    renderInventory([], [device, group, { ...point, availability: "configured", actions: ["point_read", "priority_array_read"] }]);
    const pointItem = await screen.findByTestId("inventory-treeitem-point:opaque-point");
    apiFetch.mockImplementation(async (path: string, options?: RequestInit) => {
      if (path === "/api/connectors/edge-a/read") {
        const request = JSON.parse(String(options?.body));
        return new Promise((resolve) => {
          resolveRead = (value) => resolve({ ...(value as Record<string, unknown>), request_id: request.request_id });
        });
      }
      return {};
    });
    fireEvent.click(pointItem);
    const readButton = screen.getByRole("button", { name: "Read point" });
    const priorityButton = screen.getByRole("button", { name: "Read priority array" });
    fireEvent.click(readButton);
    fireEvent.click(readButton);
    fireEvent.click(priorityButton);
    expect(apiFetch.mock.calls.filter(([path]) => String(path).includes("/read"))).toHaveLength(1);
    expect((readButton as HTMLButtonElement).disabled).toBe(true);
    expect((priorityButton as HTMLButtonElement).disabled).toBe(true);
    resolveRead?.({
      schema: "openfdd.connector.read.v1", request_id: "request-1", scope, ok: true,
      capability_contract: "openfdd.connector.capabilities.v1", error: null,
      result: { kind: "point", device_instance: 7, object_type: "analog-value", object_instance: 1, property_id: "present-value", type: "real", value: 71.25, quality: "good", observed_at: "2026-10-01T01:00:00Z" },
    });
    await screen.findByTestId("inventory-read-point-result");
  });

  it("cancels a selected point read and ignores its late result", async () => {
    let resolveRead: ((value: unknown) => void) | undefined;
    let readSignal: AbortSignal | undefined;
    renderInventory([], [device, group, { ...point, availability: "configured", actions: ["point_read"] }, secondPoint]);
    const firstPoint = await screen.findByTestId("inventory-treeitem-point:opaque-point");
    const secondPointItem = await screen.findByTestId("inventory-treeitem-point:opaque-point-2");
    apiFetch.mockImplementation(async (path: string, options?: RequestInit) => {
      if (path === "/api/connectors/edge-a/read") {
        readSignal = options?.signal;
        return new Promise((resolve) => { resolveRead = resolve; });
      }
      return {};
    });
    fireEvent.click(firstPoint);
    fireEvent.click(screen.getByRole("button", { name: "Read point" }));
    fireEvent.click(secondPointItem);
    expect(readSignal?.aborted).toBe(true);
    resolveRead?.({
      schema: "openfdd.connector.read.v1", request_id: "request-1", scope, ok: true,
      capability_contract: "openfdd.connector.capabilities.v1", error: null,
      result: { kind: "point", device_instance: 7, object_type: "analog-value", object_instance: 1, property_id: "present-value", type: "real", value: 71.25, quality: "good", observed_at: "2026-10-01T01:00:00Z" },
    });
    await waitFor(() => expect(screen.queryByTestId("inventory-read-point-result")).toBeNull());
    expect(screen.getByTestId("inventory-treeitem-point:opaque-point-2")).toBeTruthy();
  });

  it.each([401, 403])("shows an honest authenticated HTTP %s read failure", async (status) => {
    renderInventory([], [device, group, { ...point, availability: "configured", actions: ["point_read"] }]);
    const pointItem = await screen.findByTestId("inventory-treeitem-point:opaque-point");
    apiFetch.mockImplementation(async (path: string) => {
      if (path === "/api/connectors/edge-a/read") {
        throw Object.assign(new Error(status === 401 ? "unauthorized" : "forbidden"), { status });
      }
      return {};
    });
    fireEvent.click(pointItem);
    fireEvent.click(screen.getByRole("button", { name: "Read point" }));
    expect((await screen.findByTestId("inventory-read-error")).textContent).toContain("not authorized");
    expect(screen.queryByTestId("inventory-read-point-result")).toBeNull();
  });

  it("clears the edge and inventory when the active building changes", async () => {
    apiFetch.mockImplementation(async (path: string) => {
      if (path === "/api/tenants") {
        return {
          ok: true, active_tenant_id: "tenant-a", buildings_visible: ["building-a", "building-b"],
          tenants: [{ id: "tenant-a", name: "Tenant A", building_ids: ["building-a", "building-b"] }],
        };
      }
      if (path === "/api/edges") return {
        ok: true,
        edges: [
          { edge_id: "edge-a", site_id: "building-a" },
          { edge_id: "edge-b", site_id: "building-b" },
        ],
      };
      return {};
    });
    fetchPage.mockResolvedValue(page([device]));
    render(
      <MemoryRouter initialEntries={["/operations?site=building-a&edge=edge-a"]}>
        <ProtocolInventory protocol="bacnet" />
      </MemoryRouter>,
    );
    await screen.findByTestId("inventory-treeitem-device:opaque-device");
    fireEvent.change(screen.getByTestId("inventory-building"), { target: { value: "building-b" } });
    await waitFor(() => expect((screen.getByTestId("inventory-edge") as HTMLSelectElement).value).toBe(""));
    expect(screen.queryByTestId("inventory-treeitem-device:opaque-device")).toBeNull();
  });

  it("does not issue inventory calls without an explicit edge selection", async () => {
    apiFetch.mockImplementation(async (path: string) => {
      if (path === "/api/tenants") return {
        ok: true,
        active_tenant_id: "tenant-a",
        buildings_visible: ["building-a"],
        tenants: [{ id: "tenant-a", name: "Tenant A", building_ids: ["building-a"] }],
      };
      if (path === "/api/edges") return { ok: true, edges: [{ edge_id: "edge-a", site_id: "building-a" }] };
      return {};
    });
    render(
      <MemoryRouter initialEntries={["/operations?site=building-a"]}>
        <ProtocolInventory protocol="haystack" />
      </MemoryRouter>,
    );
    await screen.findByTestId("inventory-edge");
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(fetchPage).not.toHaveBeenCalled();
  });

  it("offers broker-free configured capability edges without telemetry registration", async () => {
    apiFetch.mockImplementation(async (path: string) => {
      if (path === "/api/tenants") return {
        ok: true,
        active_tenant_id: "tenant-a",
        buildings_visible: ["building-a"],
        tenants: [{ id: "tenant-a", name: "Tenant A", building_ids: ["building-a"] }],
      };
      if (path === "/api/edges") return { ok: true, edges: [] };
      return {};
    });
    fetchPage.mockResolvedValue(page([device]));
    render(
      <MemoryRouter initialEntries={["/operations?site=building-a&edge=edge-configured"]}>
        <ProtocolInventory protocol="bacnet" capabilityEdgeIds={["edge-configured"]} />
      </MemoryRouter>,
    );
    expect((await screen.findByTestId("inventory-edge") as HTMLSelectElement).value).toBe("edge-configured");
    await waitFor(() => expect(fetchPage).toHaveBeenCalledWith(expect.objectContaining({
      scope: { tenant_id: "tenant-a", building_id: "building-a", edge_id: "edge-configured" },
    })));
  });

  it("requires an explicit load-more action for continuation pages", async () => {
    apiFetch.mockImplementation(async (path: string) => {
      if (path === "/api/tenants") return {
        ok: true,
        active_tenant_id: "tenant-a",
        buildings_visible: ["building-a"],
        tenants: [{ id: "tenant-a", name: "Tenant A", building_ids: ["building-a"] }],
      };
      if (path === "/api/edges") return { ok: true, edges: [{ edge_id: "edge-a", site_id: "building-a" }] };
      return {};
    });
    fetchPage
      .mockResolvedValueOnce({ ...page([device]), next_cursor: "opaque-next" })
      .mockResolvedValueOnce(page([group]));
    render(
      <MemoryRouter initialEntries={["/operations?site=building-a&edge=edge-a"]}>
        <ProtocolInventory protocol="bacnet" />
      </MemoryRouter>,
    );
    await screen.findByTestId("inventory-load-more");
    expect(fetchPage).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await screen.findByTestId("inventory-treeitem-group:opaque-group");
    expect(fetchPage).toHaveBeenCalledTimes(2);
  });
});
