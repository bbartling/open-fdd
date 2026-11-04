/**
 * Display-only unit helpers. Historian storage stays metric-c-v2 (SI).
 * Axis labels come from `/api/historian/points` declared metadata — never a hardcoded role→SI table.
 */

export const NOT_ASSESSED_LABEL = "not assessed";

/** Contract constant mirrored from sql/contract/metric_units.json (PA_PER_IN_WC). */
export const PA_PER_IN_WC = 248.84;

const UNIT_FAMILY = {
  "°F": "temp_F",
  degF: "temp_F",
  F: "temp_F",
  fahrenheit: "temp_F",
  "°C": "temp_C",
  degC: "temp_C",
  C: "temp_C",
  celsius: "temp_C",
  "%": "pct",
  percent: "pct",
  pct: "pct",
  Pa: "static",
  pascal: "static",
  "in. w.c.": "static",
  inH2O: "static",
  in_wc: "static",
  inwc: "static",
  cfm: "flow",
  "L/s": "flow",
  lps: "flow",
  L_per_s: "flow",
  gpm: "flow",
  bool: "bool",
  boolean: "bool",
  "0/1": "bool",
  frac: "fraction",
  fraction: "fraction",
};

const ORDER_PREF = ["temp_F", "temp_C", "pct", "static", "flow", "fraction", "bool"];

const C_TO_F = (c) => (c * 9) / 5 + 32;
const F_TO_C = (f) => ((f - 32) * 5) / 9;

function token(unit) {
  return String(unit ?? "")
    .trim()
    .toLowerCase()
    .replace(/\s/g, "");
}

function isAssessed(binding) {
  return binding?.unit_assessment === "assessed";
}

/** Normalize historian row or merged model point into a binding trace object. */
export function bindingFromPoint(row) {
  if (!row) return null;
  return {
    declared_unit: row.declared_unit ?? row.unit ?? "",
    source_unit: row.source_unit ?? "",
    quantity: row.quantity ?? "",
    canonical_unit: row.canonical_unit ?? "",
    storage_unit: row.storage_unit ?? "",
    unit_assessment: row.unit_assessment ?? "",
    unit_assessment_reason: row.unit_assessment_reason ?? "",
  };
}

/** Map `${equipId}::${role}` and bare role → binding (prefer equipment-scoped). */
export function buildRoleUnitIndex(points) {
  const byKey = new Map();
  if (!Array.isArray(points)) return byKey;
  for (const p of points) {
    const binding = bindingFromPoint(p);
    if (!binding) continue;
    const role = p.role || "";
    if (role) byKey.set(role, binding);
    const equip = p.equipRef || p.equipment_id || "";
    if (equip && role) byKey.set(`${equip}::${role}`, binding);
  }
  return byKey;
}

export function lookupRoleBinding(index, equipmentId, role) {
  if (!index || !role) return null;
  if (equipmentId) {
    const scoped = index.get(`${equipmentId}::${role}`);
    if (scoped) return scoped;
  }
  return index.get(role) ?? null;
}

/**
 * Y-axis / caption unit from API declared metadata.
 * Unknown or legacy rows stay "not assessed" — never relabeled as Pa/°C from a static table.
 */
export function resolveRoleUnit(role, unitSystem = "metric", binding = null) {
  if (!isAssessed(binding)) {
    return NOT_ASSESSED_LABEL;
  }
  const declared = binding.declared_unit || binding.source_unit || "";
  const canonical = binding.canonical_unit || "";
  const qty = (binding.quantity || "").toLowerCase();

  if (qty.includes("temperature") && qty.includes("difference")) {
    return unitSystem === "imperial" ? "Δ°F" : "Δ°C";
  }
  if (qty === "absolute_temperature" || token(declared).includes("deg") || token(declared) === "c" || token(declared) === "f") {
    if (unitSystem === "imperial") return "°F";
    return "°C";
  }
  if (qty === "air_pressure" || token(declared).includes("inh2o") || token(declared).includes("inwc")) {
    return unitSystem === "imperial" ? "in. w.c." : "Pa";
  }
  if (qty === "volumetric_flow") {
    return unitSystem === "imperial" ? "cfm" : "L/s";
  }
  if (qty === "percent" || qty === "relative_humidity" || token(declared) === "%") {
    return "%";
  }
  if (qty === "fraction" || token(declared) === "frac") {
    return "frac";
  }
  if (canonical) {
    if (unitSystem === "imperial" && canonical === "Pa") return "in. w.c.";
    if (unitSystem === "imperial" && canonical === "degC") return "°F";
    if (unitSystem === "imperial" && canonical === "L_per_s") return "cfm";
    return canonical;
  }
  if (declared) return declared;
  return NOT_ASSESSED_LABEL;
}

export function unitFamily(unit) {
  const u = String(unit ?? "").trim();
  if (!u || u === NOT_ASSESSED_LABEL) return "other:not_assessed";
  return UNIT_FAMILY[u] ?? UNIT_FAMILY[token(u)] ?? `other:${u}`;
}

export function familyOrderKeys(keys) {
  const others = keys.filter((k) => !ORDER_PREF.includes(k)).sort((a, b) => a.localeCompare(b));
  const pref = ORDER_PREF.filter((k) => k !== "bool" && keys.includes(k));
  const bools = keys.includes("bool") ? ["bool"] : [];
  return [...pref, ...others, ...bools];
}

/** Convert stored SI sample to display units when binding is assessed. */
export function displayStoredValue(value, binding, unitSystem = "metric") {
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  if (!isAssessed(binding)) return n;
  const qty = (binding.quantity || "").toLowerCase();
  if (qty === "absolute_temperature") {
    return unitSystem === "imperial" ? C_TO_F(n) : n;
  }
  if (qty === "temperature_difference" || qty === "temperature_rate") {
    return unitSystem === "imperial" ? (n * 9) / 5 : n;
  }
  if (qty === "air_pressure" && unitSystem === "imperial") {
    return n / PA_PER_IN_WC;
  }
  return n;
}

export function displayTempC(valueC, unitSystem = "metric") {
  return displayStoredValue(valueC, { unit_assessment: "assessed", quantity: "absolute_temperature" }, unitSystem);
}

export function displayDeltaC(valueC, unitSystem = "metric") {
  return displayStoredValue(valueC, { unit_assessment: "assessed", quantity: "temperature_difference" }, unitSystem);
}

export function tempAxisLabel(unitSystem = "metric") {
  return unitSystem === "imperial" ? "°F" : "°C";
}

export function fahrenheitToCelsius(f) {
  return F_TO_C(f);
}

export function celsiusToFahrenheit(c) {
  return C_TO_F(c);
}

export function deltaFToDeltaC(df) {
  return (df * 5) / 9;
}

export function inWcToPa(inwc) {
  return inwc * PA_PER_IN_WC;
}

export function paToInWc(pa) {
  return pa / PA_PER_IN_WC;
}

export function cfmToLps(cfm) {
  return cfm * 0.471947;
}

export function percentToFraction(pct) {
  return pct / 100;
}

export function fractionToPercent(frac) {
  return frac * 100;
}
