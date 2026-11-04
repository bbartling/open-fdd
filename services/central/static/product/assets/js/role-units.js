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

const EXPLICIT_QUANTITY = {
  temperature: "temperature",
  temperature_delta: "temperature_delta",
  temperature_rate: "temperature_rate",
  pressure: "pressure",
  fraction: "fraction",
  percent: "percent",
  minutes: "minutes",
  hours: "hours",
  seconds: "seconds",
  boolean: "boolean",
  volumetric_flow: "volumetric_flow",
};

function unitToken(unit) {
  return String(unit ?? "")
    .trim()
    .toLowerCase()
    .replace(/\s/g, "");
}

function keySuggestsTemperatureDelta(key) {
  const k = String(key ?? "").toLowerCase();
  return k.includes("delta") || k.startsWith("eps_") || k.includes("_tol");
}

function temperatureScale(unit) {
  const t = unitToken(unit);
  if (t === "degf" || t === "f" || t === "°f") return "f";
  if (t === "degc" || t === "c" || t === "°c") return "c";
  return null;
}

function isSiAbsoluteTempToken(t) {
  return t === "degc" || t === "c" || t === "celsius";
}

function isSiDeltaToken(t) {
  return t.includes("deltac") || t === "k_diff" || t === "k";
}

function pressureToPaFactor(unit) {
  const t = unitToken(unit);
  if (t === "pa" || t === "pascal") return 1;
  if (t === "inwc" || t === "inh2o" || t === "in.w.c.") return PA_PER_IN_WC;
  return null;
}

/** Infer quantity from catalog unit and parameter key. */
export function resolveQuantityKind(unit, key, explicit) {
  if (typeof explicit === "string") {
    const mapped = EXPLICIT_QUANTITY[explicit.trim().toLowerCase()];
    if (mapped) return mapped;
  }
  const token = unitToken(unit);
  if (!token) {
    if (keySuggestsTemperatureDelta(key)) return "temperature_delta";
    const k = String(key ?? "").toLowerCase();
    if (k.endsWith("_min") || k.endsWith("_minutes")) return "minutes";
    return "other";
  }
  if (pressureToPaFactor(unit) != null) return "pressure";
  if (token === "frac") return "fraction";
  if (token === "min" || token === "mins") return "minutes";
  if (token === "pct" || token === "%" || token === "percent") return "percent";
  if (token.includes("delta") || isSiDeltaToken(token)) return "temperature_delta";
  if (isSiAbsoluteTempToken(token) || token === "degf" || token === "f") {
    return keySuggestsTemperatureDelta(key) ? "temperature_delta" : "temperature";
  }
  return "other";
}

export function displayScalar(value, unit, unitSystem, kind, key) {
  const q = resolveQuantityKind(unit, key, kind);
  const token = unitToken(unit);
  if (q === "temperature" && isSiAbsoluteTempToken(token)) {
    return unitSystem === "imperial" ? celsiusToFahrenheit(value) : value;
  }
  if ((q === "temperature_delta" || q === "temperature_rate") && isSiDeltaToken(token)) {
    return unitSystem === "imperial" ? deltaCToDeltaF(value) : value;
  }
  if (q === "pressure" && (token === "pa" || token === "pascal")) {
    const factor = pressureToPaFactor("Pa");
    if (unitSystem === "imperial" && factor) return value / factor;
    return value;
  }
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

function deltaCToDeltaF(dc) {
  return (dc * 9) / 5;
}

export function storeScalar(display, unit, unitSystem, kind, key) {
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

export function displayStep(step, unit, unitSystem, kind, key) {
  const base = step != null && step > 0 ? step : 0.1;
  if (unitSystem === "metric") {
    const q = resolveQuantityKind(unit, key, kind);
    if ((q === "temperature" || q === "temperature_delta") && temperatureScale(unit) === "f") {
      return base * (5 / 9);
    }
    if (q === "pressure") {
      const factor = pressureToPaFactor(unit);
      if (factor != null && factor !== 1) return base * factor;
    }
  }
  if (unitSystem === "imperial") {
    const q = resolveQuantityKind(unit, key, kind);
    if ((q === "temperature" || q === "temperature_delta") && temperatureScale(unit) === "c") {
      return base * (9 / 5);
    }
  }
  return base;
}

export function formatTunerCaption(value, quantity) {
  if (!Number.isFinite(value)) return "";
  const q = typeof quantity === "string" ? EXPLICIT_QUANTITY[quantity] ?? quantity : quantity;
  if (q === "fraction" || q === "minutes" || q === "percent" || q === "boolean") {
    return String(value);
  }
  return String(Math.round(value * 1000) / 1000);
}

export function displayUnitLabel(unit, unitSystem, kind, key) {
  const q = resolveQuantityKind(unit, key, kind);
  const scale = temperatureScale(unit);
  if (q === "temperature_delta") {
    return unitSystem === "imperial" ? "Δ°F" : "Δ°C";
  }
  if (q === "temperature_rate") {
    return unitSystem === "imperial" ? "°F/h" : "°C/h";
  }
  if (q === "temperature") {
    if (scale === "c" || isSiAbsoluteTempToken(unitToken(unit))) {
      return unitSystem === "imperial" ? "°F" : "°C";
    }
    return unitSystem === "metric" ? "°C" : "°F";
  }
  if (q === "pressure") {
    return unitSystem === "imperial" ? "in. w.c." : "Pa";
  }
  if (q === "minutes") return "min";
  if (q === "percent") return "%";
  if (q === "fraction") return "frac";
  if (unit) return String(unit);
  return "";
}
