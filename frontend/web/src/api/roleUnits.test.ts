import { describe, expect, it } from "vitest";
import {
  celsiusToFahrenheit,
  deltaCToDeltaF,
  deltaFToDeltaC,
  displayScalar,
  displayStoredQuantity,
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
    expect(resolveQuantityKind("°F", "eps_sat")).toBe("temperature_delta");
    expect(resolveQuantityKind("degF", "flatline_tol")).toBe("temperature_delta");
    expect(deltaFToDeltaC(5)).toBeCloseTo(2.777777777777778, 5);
    expect(deltaCToDeltaF(3)).toBeCloseTo(5.4, 5);
    expect(displayScalar(5, "°F", "metric", undefined, "eps_sat")).toBeCloseTo(2.777777777777778, 5);
    expect(storeScalar(3, "°F", "metric", undefined, "eps_sat")).toBeCloseTo(5.4, 5);
    expect(displayUnitLabel("°F", "metric", undefined, "eps_sat")).toBe("Δ°C");
  });
});

function expectRoundTrip(
  stored: number,
  unit: string,
  quantity: string,
  key: string,
  system: "imperial" | "metric",
) {
  const shown = displayScalar(stored, unit, system, quantity, key);
  const back = storeScalar(shown, unit, system, quantity, key);
  expect(back).toBeCloseTo(stored, 9);
}

describe("quantity round-trips", () => {
  it("keeps pressure, fraction, temperature, temperature delta, and minutes distinct", () => {
    expect(resolveQuantityKind("inwc", "eps_dsp")).toBe("pressure");
    expect(resolveQuantityKind("frac", "eps_vfd_spd")).toBe("fraction");
    expect(resolveQuantityKind("degF", "zone_t_lo")).toBe("temperature");
    expect(resolveQuantityKind("degF", "eps_mat")).toBe("temperature_delta");
    expect(resolveQuantityKind("min", "mode_delay_min")).toBe("minutes");
    expect(resolveQuantityKind("in_wc", "duct_high_margin")).toBe("pressure");
    expect(displayUnitLabel("inwc", "imperial", "pressure", "eps_dsp")).toBe("in. w.c.");
    expect(displayUnitLabel("inwc", "metric", "pressure", "eps_dsp")).toBe("Pa");
    expect(displayUnitLabel("frac", "metric", "fraction", "eps_vfd_spd")).toBe("frac");
    expect(displayUnitLabel("frac", "imperial", "fraction", "eps_vfd_spd")).not.toBe("%");
    expect(displayUnitLabel("min", "metric", "minutes", "confirm_min")).toBe("min");
    expect(displayUnitLabel("degF", "metric", "temperature", "zone_t_lo")).toBe("°C");
    expect(displayUnitLabel("degF", "metric", "temperature_delta", "eps_mat")).toBe("Δ°C");
  });

  it.each([
    ["pressure", 0.12, "inwc", "eps_dsp"],
    ["pressure", 2.5, "psi", "head_err"],
    ["fraction", 0.13, "frac", "eps_vfd_spd"],
    ["temperature", 70, "degF", "zone_t_lo"],
    ["temperature", 32, "degF", "zone_t_lo"],
    ["temperature", 20, "degC", "zone_t_lo"],
    ["temperature_delta", 5, "degF", "eps_mat"],
    ["temperature_delta", 32, "degF", "eps_mat"],
    ["temperature_delta", -1.15, "°F", "flatline_tol"],
    ["temperature_delta", 2, "degC", "eps_mat"],
    ["minutes", 10, "min", "mode_delay_min"],
    ["minutes", 0, "min", "confirm_min"],
    ["minutes", 0.5, "min", "startup_delay_min"],
    ["temperature_rate", 1.8, "degF_per_h", "steady_fault_per_hour"],
    ["temperature_rate", 32, "degF_per_h", "steady_fault_per_hour"],
    ["percent", 15, "pct", "oa_damper_min"],
    ["hours", 4, "h", "lookback_h"],
    ["seconds", 30, "sec", "confirm_seconds"],
    ["boolean", 1, "bool", "require_operational_gate"],
    ["volumetric_flow", 1200, "cfm", "min_flow"],
    ["pressure", 1.5, "kPa", "duct_static_margin"],
    ["pressure", 40, "Pa", "duct_static_margin"],
  ] as const)(
    "round-trips %s %s %s in imperial and metric",
    (quantity, stored, unit, key) => {
      expectRoundTrip(stored, unit, quantity, key, "imperial");
      expectRoundTrip(stored, unit, quantity, key, "metric");
    },
  );

  it("does not apply the absolute-temperature offset to a delta, fraction, or minutes", () => {
    expect(displayScalar(32, "degF", "metric", "temperature_delta", "eps_mat")).toBeCloseTo(
      32 * (5 / 9),
      9,
    );
    expect(displayScalar(32, "degF", "metric", "temperature_delta", "eps_mat")).not.toBeCloseTo(0, 5);
    expect(displayScalar(32, "degF", "metric", "temperature", "zone_t_lo")).toBeCloseTo(0, 9);
    expect(displayScalar(32, "degF_per_h", "metric", "temperature_rate", "steady_fault_per_hour")).toBeCloseTo(
      32 * (5 / 9),
      9,
    );
    expect(displayScalar(15, "pct", "metric", "percent", "oa_damper_min")).toBe(15);
    expect(displayScalar(0.13, "frac", "metric", "fraction", "eps_vfd_spd")).toBe(0.13);
    expect(displayScalar(0.13, "frac", "imperial", "fraction", "eps_vfd_spd")).toBe(0.13);
    expect(displayScalar(10, "min", "metric", "minutes", "confirm_min")).toBe(10);
    expect(displayScalar(0.12, "inwc", "metric", "pressure", "eps_dsp")).toBeCloseTo(
      0.12 * 249.088908333,
      6,
    );
    expect(displayScalar(0.12, "inwc", "imperial", "pressure", "eps_dsp")).toBe(0.12);
  });

  it("converts a stored sample by quantity, not by a shared axis offset", () => {
    expect(displayStoredQuantity(22.22222222222222, "absolute_temperature", "degC", "metric")).toBeCloseTo(
      22.22222222222222,
      9,
    );
    expect(displayStoredQuantity(22.22222222222222, "absolute_temperature", "degC", "imperial")).toBeCloseTo(
      72,
      6,
    );
    expect(displayStoredQuantity(32, "absolute_temperature", "°F", "metric")).toBe(0);
    expect(displayStoredQuantity(32, "dry_bulb_temperature", "°F", "metric")).toBe(0);
    expect(displayStoredQuantity(32, "wet_bulb_temperature", "°F", "metric")).toBe(0);
    expect(displayStoredQuantity(10, "temperature_difference", "°F", "metric")).toBeCloseTo(
      10 * (5 / 9),
      9,
    );
    expect(displayStoredQuantity(10, "temperature_delta", "°F", "metric")).not.toBeCloseTo(0, 5);
    expect(displayStoredQuantity(0.12, "air_pressure", "in. w.c.", "metric")).toBeCloseTo(
      0.12 * 249.088908333,
      6,
    );
    expect(displayStoredQuantity(0.4, "fraction", "", "metric")).toBe(0.4);
    expect(displayStoredQuantity(15, "percent", "%", "metric")).toBe(15);
    expect(displayStoredQuantity(10, "minutes", "min", "metric")).toBe(10);
    expect(displayStoredQuantity(70, "absolute_temperature", "°F", "imperial")).toBe(70);
    expect(displayStoredQuantity(10, "temperature_difference", "°F", "imperial")).toBe(10);
  });
});

/** T1284-5 — SI API fixtures convert at display time (#1284 W5a). */
describe("T1284-5 display preference", () => {
  it("shows °C in SI mode and °F in imperial for absolute SI storage", () => {
    const c = 21.0;
    expect(displayStoredQuantity(c, "absolute_temperature", "degC", "metric")).toBeCloseTo(21, 9);
    expect(displayStoredQuantity(c, "absolute_temperature", "degC", "imperial")).toBeCloseTo(69.8, 6);
    expect(displayUnitLabel("degC", "metric", "temperature")).toBe("°C");
    expect(displayUnitLabel("degC", "imperial", "temperature")).toBe("°F");
  });

  it("converts a 10 K delta to 18 °F in imperial (not 50 °F)", () => {
    const shown = displayScalar(10, "K_diff", "imperial", "temperature_difference", "eps_mat");
    expect(shown).toBeCloseTo(18, 9);
    expect(shown).not.toBeCloseTo(50, 3);
    expect(displayScalar(10, "K_diff", "metric", "temperature_difference", "eps_mat")).toBeCloseTo(
      10,
      9,
    );
  });
});
