import { describe, expect, it } from "vitest";
import {
  extractPointDiscoveryObjects,
  extractWhoisDevices,
  parseDeviceInstanceFromIAmIdentifier,
  parseDeviceInstanceFromWhoisRow,
} from "./bacnet-discovery-parse";
import type { PointDiscoveryResponse, WhoIsResponse } from "./crud-api";

describe("parseDeviceInstanceFromIAmIdentifier", () => {
  it("parses device:instance", () => {
    expect(parseDeviceInstanceFromIAmIdentifier("device:12345")).toBe(12345);
  });
  it("parses device,instance", () => {
    expect(parseDeviceInstanceFromIAmIdentifier("device,999")).toBe(999);
  });
  it("falls back to last plausible number", () => {
    expect(parseDeviceInstanceFromIAmIdentifier("object 12 device 4000")).toBe(4000);
  });
  it("returns null for empty", () => {
    expect(parseDeviceInstanceFromIAmIdentifier("")).toBeNull();
  });
  it("returns null for out of range", () => {
    expect(parseDeviceInstanceFromIAmIdentifier("device:99999999")).toBeNull();
  });
});

describe("parseDeviceInstanceFromWhoisRow", () => {
  it("uses i-am-device-identifier", () => {
    expect(
      parseDeviceInstanceFromWhoisRow({
        "i-am-device-identifier": "device:42",
        "device-address": "1:2:3",
      }),
    ).toBe(42);
  });
});

describe("extractWhoisDevices", () => {
  it("reads devices from nested result.data", () => {
    const res: WhoIsResponse = {
      body: { result: { data: { devices: [{ "i-am-device-identifier": "device:1" }] } } },
    };
    expect(extractWhoisDevices(res)).toHaveLength(1);
  });
});

describe("extractPointDiscoveryObjects", () => {
  it("maps objects array", () => {
    const res: PointDiscoveryResponse = {
      body: {
        result: {
          data: {
            objects: [{ object_identifier: "analogInput:1", name: "SAT", commandable: false }],
          },
        },
      },
    };
    const rows = extractPointDiscoveryObjects(res);
    expect(rows).toEqual([
      { object_identifier: "analogInput:1", name: "SAT", commandable: false },
    ]);
  });
});
