import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  NOT_ASSESSED_LABEL,
  PA_PER_IN_WC,
  buildRoleUnitIndex,
  celsiusToFahrenheit,
  deltaFToDeltaC,
  displayDeltaC,
  displayStoredValue,
  displayTempC,
  fahrenheitToCelsius,
  fractionToPercent,
  inWcToPa,
  lookupRoleBinding,
  percentToFraction,
  resolveRoleUnit,
  unitFamily,
} from "./role-units.js";

describe("role-units API binding labels", () => {
  const assessedPressure = {
    role: "duct_static",
    equipRef: "AHU_1",
    declared_unit: "inH2O",
    source_unit: "inH2O",
    quantity: "air_pressure",
    canonical_unit: "Pa",
    storage_unit: "Pa",
    unit_assessment: "assessed",
  };

  it("labels assessed duct pressure from declared metadata, not a static Pa default", () => {
    assert.equal(resolveRoleUnit("duct_static", "metric", assessedPressure), "Pa");
    assert.equal(resolveRoleUnit("duct_static", "imperial", assessedPressure), "in. w.c.");
  });

  it("unknown legacy rows render not assessed, never Pa", () => {
    const legacy = {
      declared_unit: "inH2O",
      quantity: "air_pressure",
      unit_assessment: "not_assessed",
      unit_assessment_reason: "legacy_unconverted",
    };
    assert.equal(resolveRoleUnit("duct_static", "metric", legacy), NOT_ASSESSED_LABEL);
    assert.equal(unitFamily(NOT_ASSESSED_LABEL), "other:not_assessed");
  });

  it("sensor and setpoint share unit family when both assessed", () => {
    const sp = {
      ...assessedPressure,
      role: "duct_static_sp",
    };
    const index = buildRoleUnitIndex([assessedPressure, sp]);
    const sensor = lookupRoleBinding(index, "AHU_1", "duct_static");
    const setpoint = lookupRoleBinding(index, "AHU_1", "duct_static_sp");
    assert.equal(
      unitFamily(resolveRoleUnit("duct_static", "metric", sensor)),
      unitFamily(resolveRoleUnit("duct_static_sp", "metric", setpoint)),
    );
  });

  it("1 inH2O uses contract 248.84 Pa (249.0889 is reference-only)", () => {
    assert.equal(inWcToPa(1), PA_PER_IN_WC);
    assert.ok(Math.abs(inWcToPa(1) - 249.0889) > 0.2);
  });

  it("F/C absolute and delta conversions", () => {
    assert.ok(Math.abs(fahrenheitToCelsius(68) - 20) < 1e-9);
    assert.ok(Math.abs(celsiusToFahrenheit(20) - 68) < 1e-9);
    assert.ok(Math.abs(deltaFToDeltaC(9) - 5) < 1e-9);
    assert.equal(displayTempC(20, "imperial"), 68);
    assert.equal(displayDeltaC(5, "imperial"), 9);
  });

  it("RH percent vs fraction stay distinct", () => {
    assert.equal(percentToFraction(50), 0.5);
    assert.equal(fractionToPercent(0.5), 50);
    const rh = {
      quantity: "relative_humidity",
      declared_unit: "%",
      unit_assessment: "assessed",
      canonical_unit: "percent_0_100",
    };
    assert.equal(resolveRoleUnit("oa_h", "metric", rh), "%");
    const frac = {
      quantity: "fraction",
      declared_unit: "frac",
      unit_assessment: "assessed",
    };
    assert.equal(resolveRoleUnit("oa_frac", "metric", frac), "frac");
  });

  it("displayStoredValue converts assessed SI pressure to imperial", () => {
    const pa = inWcToPa(1.214);
    const shown = displayStoredValue(pa, assessedPressure, "imperial");
    assert.ok(Math.abs(shown - 1.214) < 1e-6);
  });
});
