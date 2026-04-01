import { describe, it, expect, vi, beforeEach } from "vitest";
import * as api from "@/lib/api";
import {
  bacnetReadProperty,
  bacnetReadMultiple,
  bacnetWriteProperty,
  bacnetSupervisoryLogicChecks,
  bacnetReadPointPriorityArray,
} from "@/lib/crud-api";

describe("BACnet proxy API helpers", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "apiFetch").mockResolvedValue({ ok: true } as never);
  });

  it("bacnetReadProperty posts to /bacnet/read_property with gateway query", async () => {
    await bacnetReadProperty(
      {
        request: {
          device_instance: 1,
          object_identifier: "ai,1",
          property_identifier: "present-value",
        },
      },
      "default",
    );
    expect(api.apiFetch).toHaveBeenCalledWith(
      "/bacnet/read_property?gateway=default",
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining("device_instance"),
      }),
    );
  });

  it("bacnetWriteProperty serializes JSON body", async () => {
    await bacnetWriteProperty(
      {
        request: {
          device_instance: 2,
          object_identifier: "ao,1",
          value: null,
          priority: 1,
        },
      },
      "0",
    );
    expect(api.apiFetch).toHaveBeenCalledWith(
      "/bacnet/write_property?gateway=0",
      expect.any(Object),
    );
    const body = JSON.parse(
      (vi.mocked(api.apiFetch).mock.calls[0][1] as { body: string }).body,
    );
    expect(body.request.value).toBeNull();
    expect(body.request.priority).toBe(1);
  });

  it("bacnetSupervisoryLogicChecks uses instance shape", async () => {
    await bacnetSupervisoryLogicChecks({ instance: { device_instance: 99 } }, "default");
    const raw = (vi.mocked(api.apiFetch).mock.calls[0][1] as { body: string }).body;
    expect(JSON.parse(raw).instance.device_instance).toBe(99);
  });

  it("bacnetReadPointPriorityArray posts request wrapper", async () => {
    await bacnetReadPointPriorityArray(
      { request: { device_instance: 3, object_identifier: "ao,2" } },
      "default",
    );
    expect(api.apiFetch).toHaveBeenCalledWith(
      "/bacnet/read_point_priority_array?gateway=default",
      expect.any(Object),
    );
  });

  it("bacnetReadMultiple forwards request array", async () => {
    await bacnetReadMultiple(
      {
        request: {
          device_instance: 1,
          requests: [{ object_identifier: "ai,1", property_identifier: "present-value" }],
        },
      },
      "default",
    );
    const body = JSON.parse(
      (vi.mocked(api.apiFetch).mock.calls[0][1] as { body: string }).body,
    );
    expect(body.request.requests).toHaveLength(1);
  });
});
