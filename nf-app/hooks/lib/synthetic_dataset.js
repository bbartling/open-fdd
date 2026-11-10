"use strict";
/**
 * Deterministic synthetic input for the SQL engines (tests/engines.test.mjs, scripts/nf/measure_engines.mjs).
 * Not used by the hooks at run time. Same `input` shape as engines.js `load()`.
 *
 *   buildDataset(pack, { equipments: 2, days: 3, stepSeconds: 300, gaps: true, duplicateRole: true })
 *
 * ALL VALUES ARE SI (degC, delta-degC, Pa, L/s, percent): the rules never convert units. The F/inwc/cfm numbers below
 * are written through the C(), D(), PA and LPS helpers so each physical operating point is easy to read.
 *
 * Every contract history column gets a signal (sine / step patterns) so rules have something to chew on;
 * equipment index 1 is the "sick" one (fan cmd vs status mismatch, stuck damper, low duct static, web OAT
 * disagreement, a data gap, ...), index 0 is mostly healthy with a few null columns.
 */

// imperial operating points -> SI (the dataset itself is SI only)
const C = (f) => ((f - 32) * 5) / 9;     // absolute degF -> degC
const D = (df) => (df * 5) / 9;          // delta degF -> delta degC
const PA = 248.84;                       // Pa per in.w.c.
const LPS = 0.471947;                    // L/s per cfm
const GPM = 0.0630902;                   // L/s per gpm
const PSI = 6894.757;                    // Pa per psi

const T0 = Date.UTC(2026, 0, 5, 0, 0, 0); // Monday 00:00 UTC

// Input contract (sql/fdd/role_scales.json): STATUS columns are 0/1, PERCENT columns are FRACTIONS 0-1 (a stored 1 is
// 100 %), humidity is %RH 0-100, everything else physical SI. The base waves below are written in percent for
// readability and divided by 100 for the PERCENT columns in baseSignal().
const STATUS = new Set(["fan_status", "pump_status", "chw_pump_status", "chiller_status", "compressor_status", "clg_available",
  "loop_enabled", "building_ahu_load_satisfied", "building_zone_load_satisfied"]);
const PERCENT = new Set(["fan_cmd", "damper_cmd", "damper_pct", "oa_damper_pct", "clg_valve_pct", "htg_valve_pct",
  "reheat_valve_pct", "chw_pump_cmd", "cw_pump_cmd", "return_fan", "chiller_cmd", "tower_fan_cmd"]);
const HUMIDITY = new Set(["oa_h", "ra_h", "zone_rh", "ma_h", "sa_h"]);

const wave = (i, period, phase = 0) => Math.sin((2 * Math.PI * i) / period + phase);
const square = (i, period, duty = 0.5) => ((i % period) / period < duty ? 1 : 0);

function hashCode(s) { let h = 7; for (let k = 0; k < s.length; k++) h = (h * 31 + s.charCodeAt(k)) % 100003; return h; }

/** Value of history column `col` for equipment index e at step i (hour-of-day h, occupied flag occ). */
function signal(col, e, i, h, occ, step) {
  const v = baseSignal(col, e, i, h, occ, step);
  if (e !== 1 || v === null) return v;
  // fault-injection windows on the sick unit (per day): A = hot, hard-working coil/fan; B = closed dampers, mixed = outdoor air
  const d = i % 288;
  if (d >= 100 && d < 180) {
    switch (col) {
      case "fan_cmd": return 1;
      case "mat": return v - D(15);
      case "htg_valve_pct": return 1;
      case "sat": return v - D(12);
      case "chw_return_t": return baseSignal("chw_supply_t", e, i, h, occ, step) + D(1);
      case "chw_pump_status": case "pump_status": case "chw_pump_cmd": return 1;
      case "duct_static": return 0.5 * PA;
      default:
    }
  }
  if (d >= 200 && d < 260) {
    switch (col) {
      case "oa_damper_pct": case "damper_pct": case "damper_cmd": return 0;
      case "mat": return baseSignal("oa_t", e, i, h, occ, step) + D(0.2);
      case "fan_cmd": return 0.8;
      case "sat": return C(70);
      case "sat_sp": return C(55);
      default:
    }
  }
  return v;
}

function baseSignal(col, e, i, h, occ, step) {
  const v = percentSignal(col, e, i, h, occ, step);
  return v !== null && PERCENT.has(col) ? v / 100 : v;
}

function percentSignal(col, e, i, h, occ, step) {
  const sick = e === 1;
  const seed = hashCode(col);
  const oa = C(48) + D(24) * wave(h, 24, -2.2) + D(2) * wave(i, 17);
  switch (col) {
    case "oa_t": return oa;
    case "web_oa_t": return e === 0 ? null : oa + (i % 288 > 120 && i % 288 < 200 ? D(9) : D(0.4)); // OAT-METEO disagreement
    case "web_oa_dp": return e === 0 ? null : oa - D(12);
    case "web_wb_t": return oa - D(5);
    case "oa_h": return 55 + 30 * wave(h, 24, 1);
    case "rat": return C(72) + D(0.8) * wave(i, 40);
    case "zone_t": return sick ? C(72) + D(7) * wave(i, 150) + (occ ? 0 : -D(6)) : C(72) + D(1.5) * wave(i, 60);
    case "zone_air_temp_sp": return occ ? C(72) : C(66);
    case "cooling_sp": return C(75);
    case "heating_sp": return C(69);
    case "mat": return 0.3 * oa + 0.7 * (C(72) + D(0.8) * wave(i, 40)) + (sick ? D(6) * square(i, 90, 0.3) : 0);
    case "sat": return sick ? C(55) + D(10) * wave(i, 70) + D(4) * wave(i, 7) : C(55) + D(1.2) * wave(i, 50);
    case "sat_sp": return occ ? C(55) : C(60);
    case "ahu_sat": return C(55) + D(1) * wave(i, 55);
    case "preheat_leave_t": return C(50) + D(5) * wave(i, 90);
    case "fan_cmd": return occ ? (sick ? 80 : 65 + 20 * wave(i, 120)) : 0;
    case "fan_status": {
      if (!occ) return sick && i % 288 > 40 && i % 288 < 70 ? 1 : 0; // running while the schedule says off
      return sick && i % 288 > 130 && i % 288 < 190 ? 0 : 1; // commanded on, proven off
    }
    case "damper_cmd": return occ ? (sick ? 10 : 20 + 70 * Math.abs(wave(i, 180))) : 0;
    case "damper_pct": return occ ? (sick ? 10 : 20 + 68 * Math.abs(wave(i, 180))) : 0;
    case "oa_damper_pct": return occ ? (sick ? 10 : 15 + 80 * Math.abs(wave(i, 200))) : 0;
    case "duct_static": return PA * (sick ? 0.6 + 0.2 * wave(i, 30) : 1.5 + 0.1 * wave(i, 45));
    case "duct_static_sp": return 1.5 * PA;
    case "static_reset_request": return Math.round(3 * Math.abs(wave(i, 160)));
    case "clg_valve_pct": return sick ? 30 + 60 * Math.abs(wave(i, 110)) : (occ ? 40 * Math.abs(wave(i, 220)) : 0);
    case "htg_valve_pct": return occ ? 30 * Math.max(0, wave(i, 260, 3)) : (sick ? 25 : 0);
    case "reheat_valve_pct": return sick ? 70 * square(i, 96, 0.5) : 20 * Math.max(0, wave(i, 150));
    case "vav_discharge_t": return C(58) + D(12) * square(i, 80, 0.35);
    case "vav_inlet_t": return C(55) + D(2) * wave(i, 70);
    case "vav_total_flow": return LPS * (900 + 400 * wave(i, 100));
    case "zone_flow": return LPS * (sick ? 120 + 30 * wave(i, 90) : 250 + 80 * wave(i, 130));
    case "min_flow_sp": return LPS * 150;
    case "zone_co2": return 600 + 400 * Math.abs(wave(i, 140)) + (occ ? 150 : 0);
    case "cooling_coil_entering_temp": return C(60) + D(3) * wave(i, 50);
    case "cooling_coil_leaving_temp": return C(55) + D(2) * wave(i, 50) + (sick ? D(4) : 0);
    case "heating_coil_entering_temp": return C(55) + D(3) * wave(i, 66);
    case "heating_coil_leaving_temp": return C(75) + D(4) * wave(i, 66);
    case "chw_supply_t": return C(44) + D(2) * wave(i, 95);
    case "chw_return_t": return C(52) + D(3) * wave(i, 95, 0.4);
    case "chw_supply_sp": return C(44);
    case "chw_dp": return PSI * (10 + 3 * wave(i, 85));
    case "chw_dp_sp": return PSI * 11;
    case "chw_flow": return GPM * (300 + 120 * wave(i, 120));
    case "chw_reset_request_sum": return Math.round(4 * Math.abs(wave(i, 210)));
    case "hw_supply_t": return C(150) + D(12) * wave(i, 130);
    case "hw_return_t": return C(130) + D(8) * wave(i, 130, 0.3);
    case "hw_reset_request_sum": return Math.round(3 * Math.abs(wave(i, 190)));
    case "cw_supply_t": return e === 0 ? null : C(80) + D(4) * wave(i, 100);
    case "electric_kw": return 40 + 15 * wave(i, 288, 0.5);
    case "kwh": return (40 + 15 * wave(i, 288, 0.5)) * step / 3600;
    case "electric_kwh": return null;
    case "chiller_amps": case "chiller_current": return 80 + 30 * wave(i, 100);
    case "chiller_power": return 100 + 35 * wave(i, 100);
    case "ra_h": return 45 + 5 * wave(i, 80);
    case "zone_rh": return 48 + 8 * wave(i, 120);
    case "ma_h": return 50 + 5 * wave(i, 90);
    case "sa_h": return 70 + 5 * wave(i, 60);
    default:
      if (STATUS.has(col)) return square(i + (seed % 50), 60 + (seed % 90), 0.5 + (sick ? 0.2 : 0)) * (occ ? 1 : 0.0);
      if (PERCENT.has(col)) return 50 + 45 * wave(i, 60 + (seed % 120), seed);
      if (HUMIDITY.has(col)) return 50 + 15 * wave(i, 90 + (seed % 50), seed);
      return 50 + 20 * wave(i, 97 + (seed % 60), seed % 7);
  }
}

function buildDataset(pack, { equipments = 2, days = 3, stepSeconds = 300, gaps = true, duplicateRole = true } = {}) {
  const histCols = pack.contract.history.filter((c) => c.name !== "equipment_id" && c.name !== "timestamp_utc");
  const history = [];
  const equipmentIds = Array.from({ length: equipments }, (_, e) => `AHU-${e + 1}`);
  const steps = Math.round((days * 86400) / stepSeconds);
  for (let e = 0; e < equipments; e++) {
    for (let i = 0; i < steps; i++) {
      // a 3.3 h hole in the sick unit's second day: gaps longer than MAX_GAP_HOURS break streaks
      if (gaps && e % 2 === 1 && i >= 400 && i < 440) continue;
      const ts = T0 + i * stepSeconds * 1000;
      const h = ((i * stepSeconds) / 3600) % 24;
      const occ = h >= 6 && h < 20;
      const row = { equipment_id: equipmentIds[e], ts };
      for (const c of histCols) {
        if (c.type === "text") {
          // occ_mode: text tokens for unit 0, numeric strings (try_double path) for unit 1
          row[c.name] = e === 0 ? (occ ? "Occupied" : "Unoccupied") : (occ ? "1.0" : "0.0");
        } else {
          const v = signal(c.name, e, i, h, occ, stepSeconds);
          row[c.name] = v === null ? null : Math.round(v * 1e6) / 1e6;
        }
      }
      // sensor dropouts (NULL cells) on unit 0
      if (e === 0 && i % 97 === 5) { row.sat = null; row.mat = null; }
      history.push(row);
    }
  }
  const weather = [];
  for (let i = 0; i < steps; i += 4) { // every 20 min at 5 min history
    const ts = T0 + i * stepSeconds * 1000;
    const h = ((i * stepSeconds) / 3600) % 24;
    const oa = C(48) + D(24) * wave(h, 24, -2.2);
    weather.push({ ts, oa_t: oa, web_oa_t: oa + D(0.6), web_oa_dp: oa - D(11) });
  }
  // SI units as the hook declares them after toSI(); one imperial and one missing unit prove the SV-* gate masks, never converts.
  const mixed = [["oa_t", "°C"], ["mat", "°C"], ["zone_t", "°C"], ["rat", "°C"], ["sat", "°C"],
    ["chw_supply_t", "°C"], ["chw_return_t", "°C"], ["hw_supply_t", null], ["hw_return_t", "°F"],
    ["oa_h", "%"], ["ra_h", "%"], ["zone_rh", "%"], ["ma_h", "%"], ["sa_h", "%"], ["duct_static", "Pa"]];
  const authorizedSeries = [];
  const sensorHistory = [];
  const equipment = [];
  for (const id of equipmentIds) {
    equipment.push({ building_id: "site-1", equipment_id: id });
    for (const [role, unit] of mixed) authorizedSeries.push({ site_id: "site-1", equipment_id: id, role, unit });
    const series = mixed.map(([role, unit]) => ({ series_id: `series-${id}-${role}`, role, unit }));
    if (duplicateRole) series.push({ series_id: `series-${id}-sat-duplicate`, role: "sat", unit: "°C" });
    for (const sensor of series) {
      for (const row of history) {
        if (row.equipment_id !== id) continue;
        sensorHistory.push({
          equipment_id: id, series_id: sensor.series_id, sensor_role: sensor.role, unit: sensor.unit,
          ts: row.ts, value: row[sensor.role] ?? null,
        });
      }
    }
  }
  if (duplicateRole) authorizedSeries.push({ site_id: "site-1", equipment_id: equipmentIds[0], role: "sat", unit: "°C" }); // duplicate role: excluded by the rule
  const utilityMonthly = [{ billing_period: "2026-01", kwh: 5000 }, { billing_period: "2026-02", kwh: 100 }];
  const utilityInterval = [];
  for (let i = 0; i < steps; i += 3) utilityInterval.push({ ts: T0 + i * stepSeconds * 1000, kwh: 3.3 + 1.2 * wave(i, 288) });
  return {
    historyColumns: histCols.map((c) => ({ name: c.name, type: c.type === "text" ? "text" : "double" })),
    history, weather, authorizedSeries, sensorHistory, equipment, utilityMonthly, utilityInterval,
  };
}

module.exports = { buildDataset };
