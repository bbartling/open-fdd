import { describe, expect, it } from "vitest";
import {
  celsiusToFahrenheit,
  displayScalar,
  displayUnitLabel,
  fahrenheitToCelsius,
  resolveRoleUnit,
  storeScalar,
} from "./roleUnits";

describe("roleUnits metric display", () => {
  it("relabels temperature roles in metric", () => {
    expect(resolveRoleUnit("sat")).toBe("°F");
    expect(resolveRoleUnit("sat", "metric")).toBe("°C");
    expect(resolveRoleUnit("fan_cmd", "metric")).toBe("%");
  });

  it("maps 70°F slider to ~21.1°C and back", () => {
    expect(displayScalar(70, "°F", "imperial")).toBe(70);
    expect(displayScalar(70, "°F", "metric")).toBeCloseTo(21.1, 1);
    expect(storeScalar(21.1, "°F", "metric")).toBeCloseTo(70, 0);
    expect(fahrenheitToCelsius(32)).toBe(0);
    expect(celsiusToFahrenheit(32)).toBeCloseTo(89.6, 1);
    expect(displayUnitLabel("°F", "metric")).toBe("°C");
  });
});
