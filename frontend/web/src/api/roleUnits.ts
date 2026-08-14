/** Cookbook snake_case roles → display unit (vibe19 DEFAULT_ROLE_UNITS adapted). */

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

export function resolveRoleUnit(
  role: string,
  unitSystem: "imperial" | "metric" = "imperial",
): string {
  const base = DEFAULT_ROLE_UNITS[role] ?? "";
  if (unitSystem === "metric" && (base === "°F" || base === "degF")) return "°C";
  return base;
}

export function isTempUnit(unit: string | undefined): boolean {
  const u = (unit || "").trim();
  return u === "°F" || u === "degF" || u === "F" || u === "°C";
}

export function fahrenheitToCelsius(f: number): number {
  return (f - 32) * (5 / 9);
}

export function celsiusToFahrenheit(c: number): number {
  return c * (9 / 5) + 32;
}

/** Slider display: registry stores °F; metric UI shows °C. */
export function displayScalar(
  value: number,
  unit: string | undefined,
  unitSystem: "imperial" | "metric",
): number {
  if (unitSystem === "metric" && isTempUnit(unit) && unit !== "°C") {
    return Math.round(fahrenheitToCelsius(value) * 10) / 10;
  }
  return value;
}

export function storeScalar(
  display: number,
  unit: string | undefined,
  unitSystem: "imperial" | "metric",
): number {
  if (unitSystem === "metric" && isTempUnit(unit) && unit !== "°C") {
    return celsiusToFahrenheit(display);
  }
  return display;
}

export function displayUnitLabel(
  unit: string | undefined,
  unitSystem: "imperial" | "metric",
): string {
  if (!unit) return "";
  if (unitSystem === "metric" && isTempUnit(unit)) return "°C";
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
  // Signals first (temps… then other:* then bool). Fault lane is appended
  // after this list — never let bool/other sort under confirmed_fault.
  const pref = ORDER_PREF.filter((k) => k !== "bool" && keys.includes(k));
  const bools = keys.includes("bool") ? ["bool"] : [];
  return [...pref, ...others, ...bools];
}
