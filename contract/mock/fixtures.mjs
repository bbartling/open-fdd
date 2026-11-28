// Synthetic fixture data for the contract mock: one site, two AHUs, three VAVs, three days of 5-minute samples,
// four rules and their daily results (FAULT, PASS, METRIC and NOT_ASSESSED). Deterministic: same data every run.
// Equipment and point names are synthetic. Values are SI.
//
// Input names, units and value types come from the canonical role vocabulary (roles/openfdd-roles.json); rule
// inputs and confirmation defaults come from the shipped rule catalog (nf-app/static/fdd-catalog.json), whose
// legacy role keys are translated through the roles file's `legacy_keys`.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const readJson = (rel) => JSON.parse(fs.readFileSync(path.join(ROOT, rel), "utf8"));
const ROLES = readJson("roles/openfdd-roles.json");
const CATALOG = readJson("nf-app/static/fdd-catalog.json");

/** role name -> {unit (QUDT local name or null), unit_display (Haystack symbol or null), value_type} */
export const ROLE = new Map(ROLES.roles.map((r) => [r.role, {
  unit: r.unit ? r.unit.replace(/^unit:/, "") : null, unit_display: r.haystack.unit ?? null, value_type: r.value_type,
}]));
const BY_LEGACY = new Map(ROLES.roles.flatMap((r) => [r.role, ...r.legacy_keys].map((k) => [k, r.role])));
const RULE_INPUT = new Set(ROLES.roles.filter((r) => r.rule_input !== false).map((r) => r.role));

function role(name) {
  const r = ROLE.get(name);
  if (!r) throw new Error(`fixture role ${name} is not in roles/openfdd-roles.json`);
  return r;
}

export const START_MS = Date.parse("2026-01-05T00:00:00Z");
export const DAYS = 3;
export const STEP_MS = 300_000;
export const END_MS = START_MS + DAYS * 86_400_000;

// Fixture users. Passwords are dev-only and documented in contract/README.md; only scrypt hashes are stored.
// Format: scrypt$N$r$p$salt$hash (base64url).
export const USERS = [
  { username: "viewer", role: "viewer", hash: "scrypt$16384$8$1$WBAWSscCGoeDx5I2__VNXQ$YxnWW4oirAVDjMJVQCZyjkJtCnCd2WjCz69vHM0jch8" },
  { username: "operator", role: "operator", hash: "scrypt$16384$8$1$hmZmoWmlcb6_gu-PEY7QjA$j0E_YakKEY8yA117y4er1we2xRXL04pPO8Z6FDjxlTs" },
  { username: "admin", role: "admin", hash: "scrypt$16384$8$1$2pOgVm3Gfbz4h91Z-afhew$hgBRgt-OIK_ear_eN4cBHOEMcv5pCR60ZUmopPd-Thc" },
];

const SITE = { id: "site-demo", name: "Demo Site" };

export const EQUIPMENT = [
  { id: "ahu-1", name: "AHU-1", kind: "ahu", site: SITE, parent_id: null },
  { id: "ahu-2", name: "AHU-2", kind: "ahu", site: SITE, parent_id: null },
  { id: "vav-1-01", name: "VAV-1-01", kind: "vav", site: SITE, parent_id: "ahu-1" },
  { id: "vav-1-02", name: "VAV-1-02", kind: "vav", site: SITE, parent_id: "ahu-1" },
  { id: "vav-2-01", name: "VAV-2-01", kind: "vav", site: SITE, parent_id: "ahu-2" },
];

// Commands and their feedback are separate roles (`*_command` vs `*_position` / `*_status`).
const AHU_ROLES = [
  "outdoor_air_intake_temperature",
  "mixed_air_temperature",
  "discharge_air_temperature",
  "discharge_air_static_pressure",
  "discharge_air_static_pressure_setpoint",
  "supply_fan_command",
  "supply_fan_speed_command",
  "supply_fan_operating_status",
  "outdoor_air_intake_damper_position_command",
  "cooling_valve_position_command",
];

const defs = [];
for (const eq of EQUIPMENT) {
  if (eq.kind === "ahu") {
    for (const input of AHU_ROLES) {
      if (eq.id === "ahu-2" && input === "cooling_valve_position_command") continue; // unbound: FC8 is NOT_ASSESSED on ahu-2
      defs.push({ id: `${eq.id}.${input}`, name: `${eq.name} ${input}`, equipment_id: eq.id,
        input: RULE_INPUT.has(input) ? input : null, ...role(input) });
    }
    if (eq.id === "ahu-1") {
      defs.push({ id: "ahu-1.filter_pressure_drop", name: "AHU-1 filter pressure drop", equipment_id: "ahu-1", input: null, unit: "PA", unit_display: "Pa", value_type: "number" });
    }
  } else {
    defs.push({ id: `${eq.id}.zone_air_temperature`, name: `${eq.name} zone_air_temperature`, equipment_id: eq.id, input: "zone_air_temperature", ...role("zone_air_temperature") });
  }
}

// Small deterministic noise in [-1, 1).
function noise(seed, i) {
  let x = (seed * 2654435761 + i * 40503) >>> 0;
  x ^= x >>> 13; x = Math.imul(x, 0x5bd1e995) >>> 0; x ^= x >>> 15;
  return (x / 0x100000000) * 2 - 1;
}

function occupied(t) {
  const h = new Date(t).getUTCHours();
  return h >= 7 && h < 19;
}

function value(def, seed, t, i) {
  const occ = occupied(t);
  const hour = (t % 86_400_000) / 3_600_000;
  const oat = 4 + 6 * Math.sin(((hour - 9) / 24) * 2 * Math.PI);
  // ahu-1, first day 13:00-14:30: the fan is at 100 % and duct static cannot reach setpoint (the FC1 fault).
  const fc1 = def.equipment_id === "ahu-1" && t >= START_MS + 13 * 3_600_000 && t < START_MS + 14.5 * 3_600_000;
  const damper = occ ? 30 + 5 * noise(seed, i) : 0;
  switch (def.input) {
    case "outdoor_air_intake_temperature": return oat + 0.3 * noise(seed, i);
    case "mixed_air_temperature": return (occ ? 0.3 * oat + 0.7 * 21 : 20) + 0.2 * noise(seed, i);
    case "discharge_air_temperature": return (occ ? 13 : 18) + 0.3 * noise(seed, i);
    case "discharge_air_static_pressure": return occ ? (fc1 ? 150 : 250) + 8 * noise(seed, i) : 0;
    case "discharge_air_static_pressure_setpoint": return occ ? 250 : 0;
    case "supply_fan_command": return occ ? 1 : 0;
    case "supply_fan_speed_command": return occ ? (fc1 ? 100 : 70 + 10 * noise(seed, i)) : 0;
    case "supply_fan_operating_status": return occ ? 1 : 0;
    case "outdoor_air_intake_damper_position_command": return damper;
    case "outdoor_air_intake_damper_position": return Math.max(0, damper - 1);
    case "cooling_valve_position_command": return occ ? Math.max(0, 20 + 10 * noise(seed, i)) : 0;
    case "zone_air_temperature": return (occ ? 22 : 19) + 0.5 * noise(seed, i);
    default: return 120 + 5 * noise(seed, i); // the unbound filter pressure drop, Pa
  }
}

// vav-2-01's sensor stops reporting halfway through the second day (a stale point).
const STALE_FROM_MS = START_MS + 1.5 * 86_400_000;

function round(v) { return Math.round(v * 1000) / 1000; }

/** @returns {{t:number, v:number}[]} */
function seriesOf(def, seed) {
  const out = [];
  const end = def.equipment_id === "vav-2-01" ? STALE_FROM_MS : END_MS;
  for (let t = START_MS, i = 0; t < end; t += STEP_MS, i++) out.push({ t, v: round(value(def, seed, t, i)) });
  return out;
}

export const POINTS = defs.map((def, seed) => {
  const series = seriesOf(def, seed + 1);
  const last = series[series.length - 1];
  return { ...def, series, last_sample_time: last ? last.t : null, last_value: last ? last.v : null };
});

/** A fixture rule built from the shipped catalog entry: inputs by role name, catalog confirmation default. */
function ruleFrom(ruleId, kind, title) {
  const c = CATALOG.rules.find((r) => r.id === ruleId);
  if (!c) throw new Error(`rule ${ruleId} is not in fdd-catalog.json`);
  const inputs = [];
  const add = (key, required) => {
    const name = BY_LEGACY.get(key);
    if (!name) throw new Error(`${ruleId}: catalog role ${key} has no role in roles/openfdd-roles.json`);
    if (!RULE_INPUT.has(name)) return;
    if (!inputs.some((x) => x.name === name)) inputs.push({ name, required, unit: role(name).unit, unit_display: role(name).unit_display });
  };
  c.required_roles.forEach((k) => add(k, true));
  c.optional_roles.forEach((k) => add(k, false));
  const confirm = kind === "fault" ? Math.round(c.confirm_seconds / 60) : null;
  return { rule_id: ruleId, title, kind, equipment_kinds: c.equipment_kinds, inputs, confirm_min: confirm, confirm_min_default: confirm };
}

export const RULES = [
  ruleFrom("AVG-ZONE-TEMP", "metric", "Average zone air temperature"),
  ruleFrom("FAN-RUNTIME-HOURS", "metric", "Supply fan running hours"),
  // FC1 gains supply_fan_speed_command (PERCENT) when the roles file flips its rule_input flag (roles 1.1.x);
  // the inputs here follow the catalog and roles file as they are.
  ruleFrom("FC1", "fault", "Duct static pressure below setpoint at full fan"),
  ruleFrom("FC8", "fault", "Discharge air vs mixed air while economizing"),
];

function result(equipment_id, rule_id, day, fields) {
  return {
    equipment_id, rule_id, subject_point_id: null,
    window_start: START_MS + day * 86_400_000, window_end: START_MS + (day + 1) * 86_400_000,
    status: "PASS", reason: null, fault_hours: null, covered_hours: null, active_hours: null, fault_pct: null, metrics: {},
    ...fields,
  };
}

const assessed = (fault) => ({ status: fault > 0 ? "FAULT" : "PASS", fault_hours: fault, covered_hours: 24, active_hours: 12, fault_pct: round((100 * fault) / 12) });
const notAssessed = (reason) => ({ status: "NOT_ASSESSED", reason });

export const RESULTS = [];
for (let day = 0; day < DAYS; day++) {
  RESULTS.push(result("ahu-1", "FC1", day, assessed(day === 0 ? 1.5 : 0)));
  RESULTS.push(result("ahu-2", "FC1", day, assessed(0)));
  RESULTS.push(result("ahu-1", "FC8", day, assessed(0)));
  RESULTS.push(result("ahu-2", "FC8", day, notAssessed("unbound_input:cooling_valve_position_command")));
  for (const ahu of ["ahu-1", "ahu-2"]) {
    RESULTS.push(result(ahu, "FAN-RUNTIME-HOURS", day, { status: "METRIC", metrics: { runtime_hours: { value: 12, unit: "HR", unit_display: "h" } } }));
  }
  for (const vav of ["vav-1-01", "vav-1-02", "vav-2-01"]) {
    const stale = vav === "vav-2-01" && day === DAYS - 1;
    RESULTS.push(result(vav, "AVG-ZONE-TEMP", day, stale
      ? notAssessed("stale_data")
      : { status: "METRIC", metrics: { mean_zone_air_temperature: { value: 20.5, unit: "DEG_C", unit_display: "°C" } } }));
  }
}
