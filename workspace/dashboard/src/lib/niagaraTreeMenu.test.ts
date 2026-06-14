import { describe, expect, it } from "vitest";
import {
  buildDeviceContextMenuItems,
  buildPointContextMenuItems,
  formatNiagaraValue,
  preserveNiagaraOrd,
} from "./niagaraTreeMenu";
import type { NiagaraDevice, NiagaraPoint } from "./niagara-api";

const device: NiagaraDevice = {
  station_id: "bench",
  station_name: "Bench",
  station_url: "https://192.168.204.11",
  point_count: 2,
  points: [],
};

const point: NiagaraPoint = {
  station_id: "bench",
  point_ord: "slot:/Drivers/BacnetNetwork/BENS$20BENCHTEST$20BOX/points/OA$2dT",
  point_name: "OA-T",
  value: 76.18,
  status: "{ok}",
};

describe("preserveNiagaraOrd", () => {
  it("keeps $20 and $2d encoding", () => {
    const ord = "slot:/Drivers/BENS$20BOX/OA$2dT";
    expect(preserveNiagaraOrd(ord)).toBe(ord);
    expect(preserveNiagaraOrd(ord)).toContain("$20");
    expect(preserveNiagaraOrd(ord)).toContain("$2d");
  });
});

describe("formatNiagaraValue", () => {
  it("formats booleans and null", () => {
    expect(formatNiagaraValue(false)).toBe("false");
    expect(formatNiagaraValue(null)).toBe("—");
    expect(formatNiagaraValue(72.5)).toBe("72.5");
  });
});

describe("buildPointContextMenuItems", () => {
  it("exposes read-only actions without write commands", () => {
    const items = buildPointContextMenuItems({ device, point });
    const ids = items.map((i) => i.id);
    expect(ids).toEqual(["actions", "copy-ord", "copy-name"]);
    const actions = items.find((i) => i.id === "actions")?.children?.map((c) => c.id);
    expect(actions).toEqual(["refresh-value"]);
    expect(actions).not.toContain("write");
    expect(actions).not.toContain("override");
  });
});

describe("buildDeviceContextMenuItems", () => {
  it("includes discover and refresh", () => {
    const items = buildDeviceContextMenuItems({ device });
    const actions = items.find((i) => i.id === "actions")?.children?.map((c) => c.id);
    expect(actions).toContain("discover");
    expect(actions).toContain("refresh-dev");
  });
});
