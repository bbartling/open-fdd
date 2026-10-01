import { describe, expect, it } from "vitest";
import {
  CONNECTOR_INVENTORY_CONTRACT_V1,
  InventoryContractError,
  buildConnectorInventoryRequest,
  inventoryRecordKey,
  validateConnectorInventoryResponse,
  type ConnectorInventoryRequest,
  type InventoryScope,
} from "./inventoryApi";

const scope: InventoryScope = {
  tenant_id: "tenant-opaque",
  building_id: "building/opaque",
  edge_id: "edge:opaque",
};

const request: ConnectorInventoryRequest = {
  schema: CONNECTOR_INVENTORY_CONTRACT_V1,
  request_id: "request-1",
  scope,
  protocols: ["bacnet", "modbus", "haystack"],
  page_size: 10,
};

function response(records: unknown[], overrides: Record<string, unknown> = {}) {
  return {
    schema: CONNECTOR_INVENTORY_CONTRACT_V1,
    request_id: request.request_id,
    scope: request.scope,
    protocols: [...new Set(records.map((record) => (record as { protocol: string }).protocol))],
    revision: "config-opaque-1",
    captured_at: "2026-10-01T00:00:00Z",
    provenance: "trusted_configuration",
    records,
    ...overrides,
  };
}

const device = {
  kind: "device",
  device_id: "device:opaque",
  protocol: "bacnet",
  display_name: "Device",
  availability: "configured",
  commandability: "unknown",
  actions: ["metadata_read"],
};

const point = {
  kind: "point",
  point_id: "point:opaque",
  device_id: "device:opaque",
  group_id: null,
  protocol: "bacnet",
  display_name: "Supply temperature",
  units: "degF",
  availability: "configured",
  commandability: "unknown",
  actions: ["point_read", "priority_array_read"],
  reference: {
    kind: "bacnet",
    device_instance: 7,
    object_type: "analog-value",
    object_instance: 1,
    property_id: "present-value",
  },
};

describe("inventoryApi", () => {
  it("keeps opaque ids and optional group references typed", () => {
    const parsed = validateConnectorInventoryResponse(response([device, point]), request);
    expect(parsed.records[0]).toMatchObject({ device_id: "device:opaque" });
    expect(parsed.records[1]).toMatchObject({ point_id: "point:opaque", group_id: undefined });
    expect(inventoryRecordKey(parsed.records[0])).toBe("device:device:opaque");
    expect(inventoryRecordKey(parsed.records[1])).toBe("point:point:opaque");
  });

  it("accepts pages containing three protocols without inferring labels", () => {
    const modbus = {
      ...point,
      kind: "point",
      point_id: "modbus:point",
      device_id: "modbus:device",
      protocol: "modbus",
      reference: { kind: "modbus", unit_id: 1, register: 10, function: "holding" },
      actions: ["point_read"],
    };
    const haystack = {
      ...point,
      point_id: "haystack:point",
      device_id: "haystack:device",
      protocol: "haystack",
      reference: { kind: "haystack", id: "@opaque-ref" },
      actions: ["point_read"],
    };
    const parsed = validateConnectorInventoryResponse(response([point, modbus, haystack]), request);
    expect(parsed.records.map((record) => record.protocol)).toEqual(["bacnet", "modbus", "haystack"]);
  });

  it("rejects duplicate records and response scope mismatches", () => {
    expect(() => validateConnectorInventoryResponse(response([device, device]), request))
      .toThrow("duplicate record ids");
    expect(() => validateConnectorInventoryResponse(
      response([device], { scope: { ...scope, tenant_id: "foreign" } }),
      request,
    )).toThrow("scope correlation");
  });

  it("rejects an empty page that advertises a continuation cursor", () => {
    expect(() => validateConnectorInventoryResponse(
      response([], { next_cursor: "opaque.cursor" }),
      request,
    )).toThrow("empty pages cannot continue");
  });

  it("rejects invalid references and false action availability", () => {
    expect(() => validateConnectorInventoryResponse(response([{
      ...point,
      protocol: "modbus",
    }]), request)).toThrow(InventoryContractError);
    expect(() => validateConnectorInventoryResponse(response([{
      ...point,
      availability: "unavailable",
      actions: ["point_read"],
    }]), request)).toThrow("advertises actions");
  });

  it("builds an authenticated central request with the selected scope", () => {
    const built = buildConnectorInventoryRequest({ scope, protocols: ["bacnet"], pageSize: 3, cursor: "opaque.cursor" });
    expect(built.schema).toBe(CONNECTOR_INVENTORY_CONTRACT_V1);
    expect(built.scope).toEqual(scope);
    expect(built.page_size).toBe(3);
    expect(built.cursor).toBe("opaque.cursor");
    expect(built.request_id).toMatch(/.+/);
  });
});
