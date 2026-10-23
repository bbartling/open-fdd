/** Cookbook snake_case roles → display unit + quantity-aware scalar conversion. */

export type UnitSystem = "imperial" | "metric";

/**
 * How a numeric parameter converts between display systems.
 * API tokens (`pressure`, `fraction`, `temperature`, `temperature_delta`, `minutes`)
 * are canonical. Older names remain accepted as explicit input.
 */
export type QuantityKind =
  | "pressure"
  | "fraction"
  | "temperature"
  | "temperature_delta"
  | "temperature_rate"
  | "minutes"
  | "percent"
  | "volumetric_flow"
  | "hours"
  | "seconds"
  | "boolean"
  | "dimensionless"
  | "other";

/** Inches of water column (4 °C) to pascals. Store uses the inverse of this factor. */
export const INWC_TO_PA = 249.088908333;
/** Pounds per square inch to pascals. Store uses the inverse of this factor. */
export const PSI_TO_PA = 6894.757293168;

export const DEFAULT_ROLE_UNITS: Record<string, string> = {
  sat: "°F",
  sat_sp: "°F",
  mat: "°F",
  rat: "°F",
  oa_t: "°F",
  web_oa_t: "°F",
  web_wb_t: "°F",
  web_oa_dp: "°F",
  zone_t: "°F",
  zone_flow: "cfm",
  chw_supply_t: "°F",
  chw_return_t: "°F",
  cw_supply_t: "°F",
  hw_supply_t: "°F",
  hw_return_t: "°F",
  oa_damper_pct: "%",
  clg_valve_pct: "%",
  htg_valve_pct: "%",
  fan_cmd: "%",
  return_fan: "%",
  oa_h: "%",
  fan_status: "bool",
  occ_mode: "bool",
  duct_static: "in. w.c.",
  duct_static_sp: "in. w.c.",
  elec_power: "kWh",
  gas_flow: "therm",
};

const UNIT_FAMILY: Record<string, string> = {
  "°F": "temp_F",
  degF: "temp_F",
  F: "temp_F",
  "°C": "temp_C",
  degC: "temp_C",
  "%": "pct",
  percent: "pct",
  "in. w.c.": "static",
  inWC: "static",
  in_wc: "static",
  cfm: "flow",
  bool: "bool",
  "0/1": "bool",
};

const ORDER_PREF = ["temp_F", "pct", "static", "flow", "bool"];

const DELTA_UNIT_TOKENS = new Set([
  "deltaf",
  "deltac",
  "δf",
  "δc",
  "Δ°f",
  "Δ°c",
  "degf_delta",
  "degc_delta",
  "k_diff",
]);

export function resolveRoleUnit(
  role: string,
  unitSystem: UnitSystem = "imperial",
): string {
  const base = DEFAULT_ROLE_UNITS[role] ?? "";
  if (unitSystem === "metric" && (base === "°F" || base === "degF")) return "°C";
  if (unitSystem === "metric" && base === "in. w.c.") return "Pa";
  if (unitSystem === "metric" && base === "cfm") return "L/s";
  return base;
}

export function isTempUnit(unit: string | undefined): boolean {
  const u = (unit || "").trim();
  return (
    u === "°F" ||
    u === "degF" ||
    u === "F" ||
    u === "°C" ||
    u === "degC" ||
    u === "C"
  );
}

const EXPLICIT_QUANTITY: Record<string, QuantityKind> = {
  pressure: "pressure",
  air_pressure: "pressure",
  fraction: "fraction",
  frac: "fraction",
  temperature: "temperature",
  absolute_temperature: "temperature",
  temperature_delta: "temperature_delta",
  temperature_difference: "temperature_delta",
  temperature_rate: "temperature_rate",
  minutes: "minutes",
  minute: "minutes",
  percent: "percent",
  percentage: "percent",
  volumetric_flow: "volumetric_flow",
  hours: "hours",
  seconds: "seconds",
  boolean: "boolean",
  bool: "boolean",
  dimensionless: "dimensionless",
  other: "other",
};

function unitToken(unit: string | undefined): string {
  return (unit || "").trim().toLowerCase().replace(/\s/g, "");
}

function keySuggestsTemperatureDelta(key: string | undefined): boolean {
  const k = (key || "").toLowerCase();
  return (
    k.includes("eps_") ||
    k.includes("tol") ||
    k.includes("deadband") ||
    k.includes("err") ||
    k.includes("flatline") ||
    k.endsWith("_delta") ||
    k.includes("margin")
  );
}

function isTemperatureToken(token: string): boolean {
  return token === "°f" || token === "degf" || token === "f" || token === "°c" || token === "degc" || token === "c";
}

/** Fahrenheit storage versus Celsius storage. Rate units such as degF_per_h count. */
export function temperatureScale(unit: string | undefined): "f" | "c" | null {
  const token = unitToken(unit);
  if (token.startsWith("degf") || token.startsWith("°f") || token === "f" || token.includes("deltaf")) {
    return "f";
  }
  if (token.startsWith("degc") || token.startsWith("°c") || token === "c" || token.includes("deltac")) {
    return "c";
  }
  return null;
}

function pressureToPaFactor(unit: string | undefined): number | null {
  const token = unitToken(unit);
  if (token === "inwc" || token === "in_wc" || token === "in.w.c." || token === "in.wc" || token === "inh2o") {
    return INWC_TO_PA;
  }
  if (token === "psi") return PSI_TO_PA;
  if (token === "kpa") return 1000;
  if (token === "pa") return 1;
  return null;
}

/** Infer quantity from catalog unit and parameter key. An explicit token wins. */
export function resolveQuantityKind(
  unit: string | undefined,
  key?: string,
  explicit?: QuantityKind | string | null,
): QuantityKind {
  if (typeof explicit === "string") {
    const mapped = EXPLICIT_QUANTITY[explicit.trim().toLowerCase()];
    if (mapped) return mapped;
  }
  const token = unitToken(unit);
  if (!token) {
    if (keySuggestsTemperatureDelta(key)) return "temperature_delta";
    const k = (key || "").toLowerCase();
    if (k.endsWith("_min") || k.endsWith("_minutes")) return "minutes";
    return "other";
  }
  if (pressureToPaFactor(unit) != null) return "pressure";
  if (token === "frac") return "fraction";
  if (token === "min" || token === "mins" || token === "minute" || token === "minutes") {
    return "minutes";
  }
  if (token === "pct" || token === "%" || token === "percent") return "percent";
  if (token === "degf_per_h" || token === "degc_per_h" || token === "°f/h" || token === "°c/h") {
    return "temperature_rate";
  }
  if (token === "h" || token === "hr" || token === "hours") return "hours";
  if (token === "sec" || token === "secs" || token === "s" || token === "seconds") return "seconds";
  if (token === "bool" || token === "boolean" || token === "0/1") return "boolean";
  if (token === "cfm" || token === "l/s" || token === "gpm") return "volumetric_flow";
  if (DELTA_UNIT_TOKENS.has(token) || token.includes("delta")) return "temperature_delta";
  if (isTemperatureToken(token)) {
    return keySuggestsTemperatureDelta(key) ? "temperature_delta" : "temperature";
  }
  return "other";
}

export function fahrenheitToCelsius(f: number): number {
  return (f - 32) * (5 / 9);
}

export function celsiusToFahrenheit(c: number): number {
  return c * (9 / 5) + 32;
}

export function deltaFToDeltaC(df: number): number {
  return df * (5 / 9);
}

export function deltaCToDeltaF(dc: number): number {
  return dc * (9 / 5);
}

function convertsTemperature(quantity: QuantityKind): boolean {
  return (
    quantity === "temperature" ||
    quantity === "temperature_delta" ||
    quantity === "temperature_rate"
  );
}

/**
 * Slider display. Registry values stay in pack units.
 * Absolute temperature shifts by 32; a temperature delta or rate only scales.
 * Pressure scales to pascals. Fraction and minutes are unchanged.
 * The conversion is the exact inverse of {@link storeScalar} (no display rounding).
 */
export function displayScalar(
  value: number,
  unit: string | undefined,
  unitSystem: UnitSystem,
  kind?: QuantityKind | string | null,
  key?: string,
): number {
  const q = resolveQuantityKind(unit, key, kind);
  const scale = temperatureScale(unit);
  if (q === "temperature" || q === "temperature_delta" || q === "temperature_rate") {
    const delta = q !== "temperature";
    if (unitSystem === "metric" && scale === "f") {
      return delta ? deltaFToDeltaC(value) : fahrenheitToCelsius(value);
    }
    if (unitSystem === "imperial" && scale === "c") {
      return delta ? deltaCToDeltaF(value) : celsiusToFahrenheit(value);
    }
    return value;
  }
  if (q === "pressure" && unitSystem === "metric") {
    const factor = pressureToPaFactor(unit);
    if (factor != null) return value * factor;
  }
  return value;
}

export function storeScalar(
  display: number,
  unit: string | undefined,
  unitSystem: UnitSystem,
  kind?: QuantityKind | string | null,
  key?: string,
): number {
  const q = resolveQuantityKind(unit, key, kind);
  const scale = temperatureScale(unit);
  if (q === "temperature" || q === "temperature_delta" || q === "temperature_rate") {
    const delta = q !== "temperature";
    if (unitSystem === "metric" && scale === "f") {
      return delta ? deltaCToDeltaF(display) : celsiusToFahrenheit(display);
    }
    if (unitSystem === "imperial" && scale === "c") {
      return delta ? deltaFToDeltaC(display) : fahrenheitToCelsius(display);
    }
    return display;
  }
  if (q === "pressure" && unitSystem === "metric") {
    const factor = pressureToPaFactor(unit);
    if (factor != null && factor !== 0) return display / factor;
  }
  return display;
}

/**
 * Display conversion for a stored sample. Canonical history stays °F.
 * Absolute temperature shifts; a temperature difference only scales.
 * Pressure scales to pascals. Fraction, percent, and minutes stay put.
 */
export function displayStoredQuantity(
  value: number,
  quantity: string | undefined,
  unit: string | undefined,
  unitSystem: UnitSystem,
): number {
  const q = (quantity ?? "").trim().toLowerCase();
  if (
    q === "absolute_temperature" ||
    q === "dry_bulb_temperature" ||
    q === "wet_bulb_temperature" ||
    q === "temperature"
  ) {
    return displayScalar(value, unit || "°F", unitSystem, "temperature");
  }
  if (q === "temperature_difference" || q === "temperature_delta") {
    return displayScalar(value, unit || "°F", unitSystem, "temperature_delta");
  }
  if (q === "air_pressure" || q === "pressure") {
    return displayScalar(value, unit || "in. w.c.", unitSystem, "pressure");
  }
  if (
    q === "percent" ||
    q === "fraction" ||
    q === "volumetric_flow" ||
    q === "boolean" ||
    q === "hours" ||
    q === "minutes" ||
    q === "other"
  ) {
    return value;
  }
  return displayScalar(value, unit, unitSystem);
}

/** Slider step in the same units as {@link displayScalar}. */
export function displayStep(
  step: number | undefined,
  unit: string | undefined,
  unitSystem: UnitSystem,
  kind?: QuantityKind | string | null,
  key?: string,
): number {
  const base = step != null && step > 0 ? step : 0.1;
  if (unitSystem === "metric") {
    const q = resolveQuantityKind(unit, key, kind);
    if (convertsTemperature(q) && temperatureScale(unit) === "f") {
      return base * (5 / 9);
    }
    if (q === "pressure") {
      const factor = pressureToPaFactor(unit);
      if (factor != null && factor !== 1) return base * factor;
    }
  }
  if (unitSystem === "imperial") {
    const q = resolveQuantityKind(unit, key, kind);
    if (convertsTemperature(q) && temperatureScale(unit) === "c") {
      return base * (9 / 5);
    }
  }
  return base;
}

/** Caption for a slider. Does not feed the stored value. */
export function formatTunerCaption(value: number, quantity: QuantityKind | string | null | undefined): string {
  if (!Number.isFinite(value)) return "";
  const q = typeof quantity === "string" ? EXPLICIT_QUANTITY[quantity] ?? quantity : quantity;
  if (q === "fraction" || q === "minutes" || q === "percent" || q === "boolean") {
    return String(value);
  }
  const rounded = Math.round(value * 1000) / 1000;
  return String(rounded);
}

export function displayUnitLabel(
  unit: string | undefined,
  unitSystem: UnitSystem,
  kind?: QuantityKind | string | null,
  key?: string,
): string {
  const q = resolveQuantityKind(unit, key, kind);
  const scale = temperatureScale(unit);
  if (q === "temperature_delta") {
    if (!unit && unitSystem === "imperial") return "Δ°F";
    if (scale === "c") return unitSystem === "imperial" ? "Δ°F" : "Δ°C";
    return unitSystem === "metric" ? "Δ°C" : "Δ°F";
  }
  if (q === "temperature_rate") {
    if (scale === "c") return unitSystem === "imperial" ? "°F/h" : "°C/h";
    return unitSystem === "metric" ? "°C/h" : "°F/h";
  }
  if (q === "temperature") {
    if (scale === "c") return unitSystem === "imperial" ? "°F" : "°C";
    if (scale === "f" || isTempUnit(unit)) return unitSystem === "metric" ? "°C" : "°F";
    return unitSystem === "metric" ? "°C" : "°F";
  }
  if (q === "pressure") {
    if (unitSystem === "metric" && pressureToPaFactor(unit) != null) return "Pa";
    const token = unitToken(unit);
    if (token === "psi") return "psi";
    if (token === "pa") return "Pa";
    if (token === "kpa") return "kPa";
    if (pressureToPaFactor(unit) != null) return "in. w.c.";
  }
  if (q === "fraction") return "frac";
  if (q === "minutes") return "min";
  if (q === "percent") return "%";
  if (q === "hours") return "h";
  if (q === "seconds") return "s";
  return unit ?? "";
}

export function unitFamily(unit: string): string {
  const u = (unit || "").trim();
  if (!u) return "other:unknown";
  return UNIT_FAMILY[u] ?? UNIT_FAMILY[u.toLowerCase()] ?? `other:${u}`;
}

export function familyOrderKeys(keys: string[]): string[] {
  const others = keys
    .filter((k) => !ORDER_PREF.includes(k))
    .sort((a, b) => a.localeCompare(b));
  const pref = ORDER_PREF.filter((k) => k !== "bool" && keys.includes(k));
  const bools = keys.includes("bool") ? ["bool"] : [];
  return [...pref, ...others, ...bools];
}
