import { beforeEach, describe, expect, it, vi } from "vitest";
import { CONNECTOR_READ_CONTRACT_V1, readConnectorTarget } from "./connectorReadApi";

const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock("./client", () => ({ apiFetch }));
vi.mock("./requestId", () => ({ newRequestId: () => "request-1" }));

const scope = { tenant_id: "tenant-a", building_id: "building-a", edge_id: "edge-a" };
const target = { kind: "bacnet_point" as const, device_instance: 7, object_type: "analog-input", object_instance: 1, property_id: "present-value" };

function baseResponse(result: unknown) {
  return {
    schema: CONNECTOR_READ_CONTRACT_V1,
    request_id: "request-1",
    scope,
    ok: true,
    capability_contract: "openfdd.connector.capabilities.v1",
    error: null,
    result,
  };
}

function priorityResult() {
  return {
    kind: "priority_array",
    device_instance: 7,
    object_type: "analog-output",
    object_instance: 2,
    state: "supported",
    observed_at: "2026-10-01T00:00:00Z",
    slots: Array.from({ length: 16 }, (_, index) => ({
      priority_level: index + 1,
      state: index === 0 ? "value" : "null",
      type: index === 0 ? "real" : "null",
      ...(index === 0 ? { value: 72.5 } : {}),
    })),
  };
}

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
    apiFetch.mockResolvedValueOnce(baseResponse({ kind: "point", device_instance: 8, object_type: "analog-input", object_instance: 1, property_id: "present-value", type: "real", value: 1, quality: "good", observed_at: "2026-10-01T00:00:00Z" }));
    await expect(readConnectorTarget(scope, target)).rejects.toThrow(/does not match/);
    apiFetch.mockResolvedValueOnce(baseResponse({ kind: "point", device_instance: 7, object_type: "analog-input", object_instance: 1, property_id: "present-value", value: "https://private.invalid", type: "string", quality: "good", observed_at: "2026-10-01T00:00:00Z" }));
    await expect(readConnectorTarget(scope, target)).rejects.toThrow();
    const priorityTarget = { kind: "bacnet_priority_array" as const, device_instance: 7, object_type: "analog-output", object_instance: 2 };
    apiFetch.mockResolvedValueOnce(baseResponse({ kind: "priority_array", device_instance: 7, object_type: "analog-output", object_instance: 2, state: "supported", observed_at: "2026-10-01T00:00:00Z", slots: Array.from({ length: 16 }, () => ({ priority_level: 1, state: "null", type: "null" })) }));
    await expect(readConnectorTarget(scope, priorityTarget)).rejects.toThrow(/unique/);
  });

  it("accepts all sixteen uniquely correlated typed priority slots", async () => {
    const priorityTarget = { kind: "bacnet_priority_array" as const, device_instance: 7, object_type: "analog-output", object_instance: 2 };
    apiFetch.mockResolvedValueOnce(baseResponse(priorityResult()));
    await expect(readConnectorTarget(scope, priorityTarget)).resolves.toMatchObject({
      kind: "priority_array",
      slots: expect.arrayContaining([
        expect.objectContaining({ priority_level: 1, state: "value", value: 72.5 }),
        expect.objectContaining({ priority_level: 16, state: "null" }),
      ]),
    });
  });

  it.each([
    ["request id", { request_id: "other-request" }],
    ["scope", { scope: { ...scope, building_id: "other-building" } }],
  ])("rejects a correlated response with a mismatched %s", async (_label, override) => {
    apiFetch.mockResolvedValueOnce({ ...baseResponse({ kind: "point", device_instance: 7, object_type: "analog-input", object_instance: 1, property_id: "present-value", type: "real", value: 72.5, quality: "good", observed_at: "2026-10-01T00:00:00Z" }), ...override });
    await expect(readConnectorTarget(scope, target)).rejects.toThrow(/correlation/);
  });

  it.each([401, 403])("preserves an authenticated HTTP %s read failure", async (status) => {
    apiFetch.mockRejectedValueOnce(Object.assign(new Error(status === 401 ? "unauthorized" : "forbidden"), { status }));
    await expect(readConnectorTarget(scope, target)).rejects.toMatchObject({ status });
  });

  it("rejects malformed request scope or target before issuing a read", async () => {
    await expect(readConnectorTarget({ ...scope, edge_id: "../other-edge" }, target)).rejects.toThrow(/scope/);
    await expect(readConnectorTarget(scope, { ...target, object_type: "analog/input" })).rejects.toThrow(/object_type/);
    expect(apiFetch).not.toHaveBeenCalled();
  });
});
