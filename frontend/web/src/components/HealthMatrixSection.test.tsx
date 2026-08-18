import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DataTable } from "./widgets/DataTable";
import { healthRowClass, tri } from "./HealthMatrixSection";

describe("health matrix tint", () => {
  it("maps score to broken-N classes and skips unknown", () => {
    expect(healthRowClass("1/3")).toBe("health-row--broken-1");
    expect(healthRowClass("2/3")).toBe("health-row--broken-2");
    expect(healthRowClass("3/3")).toBe("health-row--broken-3");
    expect(healthRowClass("0/3")).toBeUndefined();
    expect(healthRowClass("?/3")).toBeUndefined();
    expect(tri(null)).toBe("unknown");
    expect(tri(true)).toBe("true");
  });

  it("tints DataTable rows via data-broken", () => {
    render(
      <DataTable
        id="h"
        label="Health"
        testId="health-table"
        columns={[
          { key: "score_label", header: "Score" },
          { key: "equipment_id", header: "Equipment" },
        ]}
        rows={[
          { score_label: "0/3", equipment_id: "AHU_0" },
          { score_label: "1/3", equipment_id: "AHU_1" },
          { score_label: "3/3", equipment_id: "AHU_3" },
          { score_label: "?/3", equipment_id: "AHU_q" },
        ]}
        rowClassName={(row) => healthRowClass(row.score_label)}
      />,
    );
    const rows = screen.getByTestId("health-table").querySelectorAll("tbody tr");
    expect(rows[0].getAttribute("data-broken")).toBeNull();
    expect(rows[1].getAttribute("data-broken")).toBe("1");
    expect(rows[1].className).toContain("health-row--broken-1");
    expect(rows[2].getAttribute("data-broken")).toBe("3");
    expect(rows[3].getAttribute("data-broken")).toBeNull();
  });
});
