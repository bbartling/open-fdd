import { describe, expect, it } from "vitest";
import {
  celsiusToFahrenheit,
  deltaCToDeltaF,
  deltaFToDeltaC,
  displayScalar,
  displayUnitLabel,
  fahrenheitToCelsius,
  resolveQuantityKind,
  resolveRoleUnit,
  storeScalar,
} from "./roleUnits";

describe("roleUnits metric display", () => {
  it("relabels temperature roles in metric", () => {
    expect(resolveRoleUnit("sat")).toBe("°F");
    expect(resolveRoleUnit("sat", "metric")).toBe("°C");
    expect(resolveRoleUnit("fan_cmd", "metric")).toBe("%");
  });

  it("maps absolute 70°F slider to ~21.1°C and back", () => {
    expect(displayScalar(70, "°F", "imperial")).toBe(70);
    expect(displayScalar(70, "°F", "metric")).toBeCloseTo(21.1, 1);
    expect(storeScalar(21.1, "°F", "metric")).toBeCloseTo(70, 0);
    expect(fahrenheitToCelsius(32)).toBe(0);
    expect(celsiusToFahrenheit(32)).toBeCloseTo(89.6, 1);
    expect(displayUnitLabel("°F", "metric")).toBe("°C");
  });

  it("converts temperature differences with scale only (never ±32)", () => {
    expect(resolveQuantityKind("°F", "eps_dsp")).toBe("temperature_difference");
    expect(resolveQuantityKind("degF", "flatline_tol")).toBe("temperature_difference");
    expect(deltaFToDeltaC(5)).toBeCloseTo(2.777777777777778, 5);
    expect(deltaCToDeltaF(3)).toBeCloseTo(5.4, 5);
    expect(displayScalar(5, "°F", "metric", undefined, "eps_sat")).toBeCloseTo(2.778, 3);
    expect(storeScalar(3, "°F", "metric", undefined, "eps_sat")).toBeCloseTo(5.4, 5);
    expect(displayUnitLabel("°F", "metric", undefined, "eps_sat")).toBe("Δ°C");
  });
});
