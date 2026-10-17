/** Cookbook snake_case roles → display unit + quantity-aware scalar conversion. */

export type UnitSystem = "imperial" | "metric";

/** How a numeric parameter or series converts between display systems. */
export type QuantityKind =
  | "absolute_temperature"
  | "temperature_difference"
  | "temperature_rate"
  | "air_pressure"
  | "volumetric_flow"
  | "percent"
  | "other";

export const DEFAULT_ROLE_UNITS: Record<string, string> = {
  sat: "°F",
  sat_sp: "°F",
  mat: "°F",
  rat: "°F",
  oa_t: "°F",
  web_oa_t: "°F",
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

/** Infer quantity kind from catalog unit / param key. Prefer explicit kind. */
export function resolveQuantityKind(
  unit: string | undefined,
  key?: string,
  explicit?: QuantityKind | string | null,
): QuantityKind {
  if (explicit === "absolute_temperature") return "absolute_temperature";
  if (explicit === "temperature_difference") return "temperature_difference";
  if (explicit === "temperature_rate") return "temperature_rate";
  if (explicit === "air_pressure") return "air_pressure";
  if (explicit === "volumetric_flow") return "volumetric_flow";
  if (explicit === "percent") return "percent";

  const u = (unit || "").trim().toLowerCase();
  const k = (key || "").toLowerCase();
  if (
    DELTA_UNIT_TOKENS.has(u.replace(/\s/g, "")) ||
    u.includes("delta") ||
    k.includes("eps_") ||
    k.includes("tol") ||
    k.includes("deadband") ||
    k.includes("err") ||
    k.includes("flatline") ||
    k.endsWith("_delta") ||
    k.includes("margin")
  ) {
    if (isTempUnit(unit) || u.includes("f") || u.includes("c") || u === "") {
      return "temperature_difference";
    }
  }
  if (k.includes("rate") && isTempUnit(unit)) return "temperature_rate";
  if (isTempUnit(unit)) return "absolute_temperature";
  if (u.includes("in") && u.includes("w")) return "air_pressure";
  if (u === "cfm" || u === "l/s") return "volumetric_flow";
  if (u === "%" || u === "percent" || u === "pct") return "percent";
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

/** Slider display: registry stores pack units; metric UI shows SI. */
export function displayScalar(
  value: number,
  unit: string | undefined,
  unitSystem: UnitSystem,
  kind?: QuantityKind | string | null,
  key?: string,
): number {
  if (unitSystem !== "metric") return value;
  const q = resolveQuantityKind(unit, key, kind);
  if (q === "absolute_temperature" && isTempUnit(unit) && unit !== "°C") {
    return Math.round(fahrenheitToCelsius(value) * 10) / 10;
  }
  if (q === "temperature_difference" || q === "temperature_rate") {
    return Math.round(deltaFToDeltaC(value) * 1000) / 1000;
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
  if (unitSystem !== "metric") return display;
  const q = resolveQuantityKind(unit, key, kind);
  if (q === "absolute_temperature" && isTempUnit(unit) && unit !== "°C") {
    return celsiusToFahrenheit(display);
  }
  if (q === "temperature_difference" || q === "temperature_rate") {
    return deltaCToDeltaF(display);
  }
  return display;
}

export function displayUnitLabel(
  unit: string | undefined,
  unitSystem: UnitSystem,
  kind?: QuantityKind | string | null,
  key?: string,
): string {
  if (!unit) {
    const q = resolveQuantityKind(unit, key, kind);
    if (unitSystem === "metric" && (q === "temperature_difference" || q === "temperature_rate")) {
      return "Δ°C";
    }
    return "";
  }
  const q = resolveQuantityKind(unit, key, kind);
  if (unitSystem === "metric") {
    if (q === "temperature_difference" || q === "temperature_rate") return "Δ°C";
    if (isTempUnit(unit)) return "°C";
  }
  if (q === "temperature_difference" || q === "temperature_rate") {
    return unitSystem === "imperial" ? "Δ°F" : "Δ°C";
  }
  return unit;
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
