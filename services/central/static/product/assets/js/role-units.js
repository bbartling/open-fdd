/** Display-only unit helpers (historian stays SI). Imperial toggle deferred (Bench Viz gap). */

const DEFAULT_ROLE_UNITS = {
  sat: "°C",
  mat: "°C",
  rat: "°C",
  oa_t: "°C",
  zone_t: "°C",
  oa_damper_pct: "%",
  fan_cmd: "%",
  duct_static: "Pa",
  fan_status: "bool",
};

const UNIT_FAMILY = {
  "°F": "temp_F",
  degF: "temp_F",
  F: "temp_F",
  "°C": "temp_C",
  degC: "temp_C",
  C: "temp_C",
  "%": "pct",
  percent: "pct",
  Pa: "static",
  "in. w.c.": "static",
  cfm: "flow",
  bool: "bool",
  "0/1": "bool",
};

const ORDER_PREF = ["temp_F", "temp_C", "pct", "static", "flow", "bool"];

const C_TO_F = (c) => (c * 9) / 5 + 32;

export function resolveRoleUnit(role, unitSystem = "metric") {
  const base = DEFAULT_ROLE_UNITS[role] ?? "";
  if (unitSystem === "imperial" && base === "°C") return "°F";
  if (unitSystem === "imperial" && base === "Pa") return "in. w.c.";
  return base;
}

export function unitFamily(unit) {
  const u = String(unit ?? "").trim();
  if (!u) return "other:unknown";
  return UNIT_FAMILY[u] ?? UNIT_FAMILY[u.toLowerCase()] ?? `other:${u}`;
}

export function familyOrderKeys(keys) {
  const others = keys.filter((k) => !ORDER_PREF.includes(k)).sort((a, b) => a.localeCompare(b));
  const pref = ORDER_PREF.filter((k) => k !== "bool" && keys.includes(k));
  const bools = keys.includes("bool") ? ["bool"] : [];
  return [...pref, ...others, ...bools];
}

export function displayTempC(valueC, unitSystem = "metric") {
  const n = Number(valueC);
  if (!Number.isFinite(n)) return null;
  if (unitSystem === "imperial") return C_TO_F(n);
  return n;
}

/** Temperature deltas/rates: scale only, no +32 offset. */
export function displayDeltaC(valueC, unitSystem = "metric") {
  const n = Number(valueC);
  if (!Number.isFinite(n)) return null;
  if (unitSystem === "imperial") return (n * 9) / 5;
  return n;
}

export function tempAxisLabel(unitSystem = "metric") {
  return unitSystem === "imperial" ? "°F" : "°C";
}
