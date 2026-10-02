import { beforeEach, describe, expect, it, vi } from "vitest";
import { CONNECTOR_READ_CONTRACT_V1, readConnectorTarget } from "./connectorReadApi";

const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock("./client", () => ({ apiFetch }));
vi.mock("./requestId", () => ({ newRequestId: () => "request-1" }));

const scope = { tenant_id: "tenant-a", building_id: "building-a", edge_id: "edge-a" };
const target = { kind: "bacnet_point" as const, device_instance: 7, object_type: "analog-input", object_instance: 1, property_id: "present-value" };

describe("connectorReadApi", () => {
  beforeEach(() => apiFetch.mockReset());

  it("posts one explicitly scoped point read and validates observation correlation", async () => {
    apiFetch.mockResolvedValue({
      schema: CONNECTOR_READ_CONTRACT_V1, request_id: "request-1", scope, ok: true,
      capability_contract: "openfdd.connector.capabilities.v1", error: null,
      result: { kind: "point", device_instance: 7, object_type: "analog-input", object_instance: 1, property_id: "present-value", type: "real", value: 72.5, quality: "good", observed_at: "2026-10-01T00:00:00Z" },
    });
    await expect(readConnectorTarget(scope, target)).resolves.toMatchObject({ kind: "point", value: 72.5 });
    expect(apiFetch).toHaveBeenCalledWith("/api/connectors/edge-a/read", expect.objectContaining({ method: "POST" }));
  });

  it("rejects mismatched targets, unsafe values, and malformed priority slots", async () => {
    const base = { schema: CONNECTOR_READ_CONTRACT_V1, request_id: "request-1", scope, ok: true, capability_contract: "openfdd.connector.capabilities.v1", error: null };
    apiFetch.mockResolvedValueOnce({ ...base, result: { kind: "point", device_instance: 8, object_type: "analog-input", object_instance: 1, property_id: "present-value", type: "real", value: 1, quality: "good", observed_at: "2026-10-01T00:00:00Z" } });
    await expect(readConnectorTarget(scope, target)).rejects.toThrow(/does not match/);
    apiFetch.mockResolvedValueOnce({ ...base, result: { kind: "point", device_instance: 7, object_type: "analog-input", object_instance: 1, property_id: "present-value", value: "https://private.invalid", type: "string", quality: "good", observed_at: "2026-10-01T00:00:00Z" } });
    await expect(readConnectorTarget(scope, target)).rejects.toThrow();
    const priorityTarget = { kind: "bacnet_priority_array" as const, device_instance: 7, object_type: "analog-output", object_instance: 2 };
    apiFetch.mockResolvedValueOnce({ ...base, result: { kind: "priority_array", device_instance: 7, object_type: "analog-output", object_instance: 2, state: "supported", observed_at: "2026-10-01T00:00:00Z", slots: Array.from({ length: 16 }, () => ({ priority_level: 1, state: "null", type: "null" })) } });
    await expect(readConnectorTarget(scope, priorityTarget)).rejects.toThrow(/unique/);
  });
});
