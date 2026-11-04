import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  confirmedFaultPlotY,
  expandFddPlotRoles,
  isOatMeteoRule,
  ruleResultChartOption,
  oatMeteoFddOption,
} from "./fdd-charts.js";
import { buildRoleUnitIndex } from "./role-units.js";
import { basOverlayOption } from "./overview-rcx-charts.js";
import { rcxOptionHasFaultLane, multiEquipmentTimeseriesOption } from "./rcx-vibe-charts.js";

describe("fdd-charts", () => {
  it("confirmedFaultPlotY preserves null gaps", () => {
    assert.equal(confirmedFaultPlotY(null), null);
    assert.equal(confirmedFaultPlotY(1), 1);
    assert.equal(confirmedFaultPlotY(0), 0);
  });

  it("ruleResultChartOption stacks unit families and fault lane", () => {
    const roleUnitIndex = buildRoleUnitIndex([
      {
        equipRef: "AHU_1",
        role: "zone_t",
        quantity: "absolute_temperature",
        declared_unit: "degC",
        unit_assessment: "assessed",
        canonical_unit: "degC",
      },
      {
        equipRef: "AHU_1",
        role: "fan_cmd",
        quantity: "percent",
        declared_unit: "%",
        unit_assessment: "assessed",
      },
      {
        equipRef: "AHU_1",
        role: "duct_static",
        quantity: "air_pressure",
        declared_unit: "inH2O",
        unit_assessment: "assessed",
        canonical_unit: "Pa",
      },
    ]);
    const built = ruleResultChartOption(
      [
        {
          timestamp_utc: "2026-03-01T00:00:00Z",
          zone_t: 22,
          fan_cmd: 80,
          duct_static: 110,
        },
        {
          timestamp_utc: "2026-03-01T01:00:00Z",
          zone_t: 24,
          fan_cmd: 100,
          duct_static: 90,
        },
      ],
      {
        equipmentId: "AHU_1",
        ruleId: "FC1",
        roles: ["zone_t", "fan_cmd", "duct_static"],
        confirmedFault: [0, 1],
        roleUnitIndex,
      },
    );
    assert.ok(built.option);
    assert.ok(built.hasFaultLane);
    assert.ok(built.gridCount >= 3);
    const faultSeries = built.option.series.find((s) => s.name === "confirmed_fault");
    assert.ok(faultSeries);
    assert.equal(faultSeries.connectNulls, false);
    assert.equal(faultSeries.step, "end");
    const faultY = built.option.yAxis.find((y) => y.name === "fault");
    assert.ok(faultY);
    assert.equal(faultY.min, -0.05);
    assert.equal(faultY.max, 1.15);
  });

  it("expandFddPlotRoles adds oa_damper_pct for ECON-4", () => {
    const roles = expandFddPlotRoles(
      "ECON-4",
      ["mat", "rat", "oa_t"],
      [{ oa_damper_pct: 10 }, { oa_damper_pct: 20 }],
    );
    assert.ok(roles.includes("oa_damper_pct"));
  });

  it("OAT-METEO overlay includes fault lane", () => {
    assert.ok(isOatMeteoRule("OAT-METEO"));
    const points = [
      { timestamp_utc: "2026-07-01T00:00:00Z", bas_oat_c: 20, web_oat_c: 19 },
      { timestamp_utc: "2026-07-01T01:00:00Z", bas_oat_c: 21, web_oat_c: 20 },
    ];
    assert.ok(basOverlayOption(points, "metric"));
    const built = oatMeteoFddOption(
      points,
      ["2026-07-01T00:00:00Z", "2026-07-01T01:00:00Z"],
      [0, 1],
      { ruleId: "OAT-METEO", equipmentId: "AHU_1", roles: [] },
    );
    assert.ok(built.hasFaultLane);
    assert.ok(built.option.series.some((s) => s.name === "confirmed_fault"));
  });

  it("null fault samples stay gaps in series data", () => {
    const built = ruleResultChartOption(
      [
        { timestamp_utc: "2026-03-01T00:00:00Z", zone_t: 1 },
        { timestamp_utc: "2026-03-01T01:00:00Z", zone_t: 2 },
      ],
      {
        equipmentId: "X",
        ruleId: "R",
        roles: ["zone_t"],
        confirmedFault: [null, 1],
      },
    );
    const fault = built.option.series.find((s) => s.name === "confirmed_fault");
    assert.equal(fault.data[0][1], null);
    assert.equal(fault.data[1][1], 1);
  });
});

describe("rcx fault lane guard", () => {
  it("generic RCx options have no fault lane", () => {
    const opt = multiEquipmentTimeseriesOption(
      [{ equipment_id: "VAV_1", timestamp_utc: "2026-01-01T00:00:00Z", value_f: 72 }],
      { title: "test" },
    );
    assert.equal(rcxOptionHasFaultLane(opt), false);
  });
});
