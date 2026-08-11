import { describe, expect, it } from "vitest";
import { naturalCompare, naturalSorted } from "./naturalSort";

describe("naturalCompare", () => {
  it("orders AHU_1 before AHU_10", () => {
    const ids = ["AHU_10", "AHU_2", "AHU_1"];
    expect([...ids].sort(naturalCompare)).toEqual(["AHU_1", "AHU_2", "AHU_10"]);
  });

  it("sorts objects by equipment id", () => {
    const rows = [{ equipment_id: "AHU_10" }, { equipment_id: "AHU_1" }];
    expect(naturalSorted(rows, (r) => r.equipment_id).map((r) => r.equipment_id)).toEqual([
      "AHU_1",
      "AHU_10",
    ]);
  });
});
