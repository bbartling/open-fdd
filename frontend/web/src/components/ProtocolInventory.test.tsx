import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { ProtocolInventory } from "./ProtocolInventory";
import type { ConnectorInventoryResponse, InventoryRecord } from "../api/inventoryApi";

const { apiFetch, fetchPage } = vi.hoisted(() => ({ apiFetch: vi.fn(), fetchPage: vi.fn() }));

vi.mock("../api/client", () => ({ apiFetch }));
vi.mock("../api/inventoryApi", async () => {
  const actual = await vi.importActual<typeof import("../api/inventoryApi")>("../api/inventoryApi");
  return { ...actual, fetchConnectorInventoryPage: fetchPage };
});
vi.mock("../api/authApi", () => ({ getStoredToken: vi.fn(() => "authenticated") }));
vi.mock("../api/tenantApi", () => ({ getStoredActiveTenant: vi.fn(() => null) }));

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

function renderInventory() {
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
  fetchPage.mockResolvedValue(page([device, group, point]));
  return render(
    <MemoryRouter initialEntries={["/operations?site=building-a&edge=edge-a"]}>
      <ProtocolInventory protocol="bacnet" />
    </MemoryRouter>,
  );
}

describe("ProtocolInventory", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    fetchPage.mockReset();
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
});
