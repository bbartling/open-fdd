"use strict";
/**
 * Deterministic synthetic input for the SQL engines (tests/engines.test.mjs, scripts/nf/measure_engines.mjs).
 * Not used by the hooks at run time. Same `input` shape as engines.js `load()`.
 *
 *   buildDataset(pack, { equipments: 2, days: 3, stepSeconds: 300, gaps: true, duplicateRole: true, plantSensors: false })
 *
 * Physical inputs use SI values directly (degrees Celsius, temperature differences in kelvin, Pa, L/s).
 * Fraction and relative humidity scales follow the input contract below.
 *
 * Every contract history column gets a signal (sine / step patterns) so rules have something to chew on;
 * equipment index 1 is the "sick" one (fan cmd vs status mismatch, stuck damper, low duct static, web OAT
 * disagreement, a data gap, ...), index 0 is mostly healthy with a few null columns.
 */

const T0 = Date.UTC(2026, 0, 5, 0, 0, 0); // Monday 00:00 UTC

// Input contract: STATUS and start/stop commands are 0/1. Damper, valve and fan-speed roles are PERCENT 0-100.
// Humidity is %RH 0-100. Everything else is physical SI. percentSignal() writes command waves in 0-100;
// baseSignal() turns a start/stop command into 0/1 (at or above 50) and leaves PERCENT columns in 0-100.
const STATUS = new Set(["supply_fan_operating_status", "pump_operating_status", "chilled_water_pump_operating_status", "chiller_operating_status", "compressor_operating_status", "cooling_operating_mode_status",
  "operating_mode_status", "air_handling_unit_load_satisfied_status", "zone_load_satisfied_status",
  "boiler_operating_status", "operating_status"]);
const BOOLEAN_CMD = new Set(["supply_fan_command", "chilled_water_pump_command", "condenser_water_pump_command", "return_fan_command", "chiller_command", "cooling_tower_fan_command"]);
const PERCENT = new Set(["damper_position_command", "damper_position", "outdoor_air_intake_damper_position_command", "cooling_valve_position_command", "heating_valve_position_command",
  "terminal_unit_heating_valve_position_command", "supply_fan_speed_command"]);
const HUMIDITY = new Set(["outdoor_air_intake_relative_humidity", "return_air_relative_humidity", "zone_air_relative_humidity", "mixed_air_relative_humidity", "discharge_air_relative_humidity"]);

const wave = (i, period, phase = 0) => Math.sin((2 * Math.PI * i) / period + phase);
const square = (i, period, duty = 0.5) => ((i % period) / period < duty ? 1 : 0);

function hashCode(s) { let h = 7; for (let k = 0; k < s.length; k++) h = (h * 31 + s.charCodeAt(k)) % 100003; return h; }

/** Value of history column `col` for equipment index e at step i (hour-of-day h, occupied flag occ). */
function signal(col, e, i, h, occ, step) {
  if (col === "operating_status") {
    // the resolved run proof (#1608): every fourth unit (index 3 mod 4) has NO proof bound (NULL: gated rules are SKIPPED
    // no_run_proof); index 2 mod 4 is fed by unit 0 (its proof is that unit's fan status, like a VAV fed by an AHU); every
    // other unit proves itself by its own fan status
    if (e % 4 === 3) return null;
    return signal("supply_fan_operating_status", e % 4 === 2 ? 0 : e, i, h, occ, step);
  }
  const v = baseSignal(col, e, i, h, occ, step);
  if (e !== 1 || v === null) return v;
  // fault-injection windows on the sick unit (per day): A = hot, hard-working coil/fan; B = closed dampers, mixed = outdoor air
  const d = i % 288;
  if (d >= 100 && d < 180) {
    switch (col) {
      case "supply_fan_command": return 1;
      case "supply_fan_speed_command": return 100;
      case "mixed_air_temperature": return v - 8.333333333333;
      case "heating_valve_position_command": return 100;
      case "discharge_air_temperature": return v - 6.666666666667;
      case "return_chilled_water_temperature": return baseSignal("supply_chilled_water_temperature", e, i, h, occ, step) + 0.555555555556;
      case "chilled_water_pump_operating_status": case "pump_operating_status": case "chilled_water_pump_command": return 1;
      case "discharge_air_static_pressure": return 124.42;
      default:
    }
  }
  if (d >= 200 && d < 260) {
    switch (col) {
      case "outdoor_air_intake_damper_position_command": case "damper_position": case "damper_position_command": return 0;
      case "mixed_air_temperature": return baseSignal("outdoor_air_intake_temperature", e, i, h, occ, step) + 0.111111111111;
      case "supply_fan_command": return 1;
      case "supply_fan_speed_command": return 80;
      case "discharge_air_temperature": return 21.111111111111;
      case "discharge_air_temperature_setpoint": return 12.777777777778;
      default:
    }
  }
  return v;
}

function baseSignal(col, e, i, h, occ, step) {
  const v = percentSignal(col, e, i, h, occ, step);
  if (v === null) return null;
  if (BOOLEAN_CMD.has(col)) return v >= 50 ? 1 : 0;
  return v;
}

function percentSignal(col, e, i, h, occ, step) {
  const sick = e === 1;
  const seed = hashCode(col);
  const oa = 8.888888888889 + 13.333333333333 * wave(h, 24, -2.2) + 1.111111111111 * wave(i, 17);
  switch (col) {
    case "outdoor_air_intake_temperature": return oa;
    case "weather_service_air_temperature": return e === 0 ? null : oa + (i % 288 > 120 && i % 288 < 200 ? 5 : 0.222222222222); // OAT-METEO disagreement
    case "weather_service_air_dew_point_temperature": return e === 0 ? null : oa - 6.666666666667;
    case "weather_service_air_wet_bulb_temperature": return oa - 2.777777777778;
    case "outdoor_air_intake_relative_humidity": return 55 + 30 * wave(h, 24, 1);
    case "return_air_temperature": return 22.222222222222 + 0.444444444444 * wave(i, 40);
    case "zone_air_temperature": return sick ? 22.222222222222 + 3.888888888889 * wave(i, 150) + (occ ? 0 : -3.333333333333) : 22.222222222222 + 0.833333333333 * wave(i, 60);
    case "zone_air_temperature_setpoint": return occ ? 22.222222222222 : 18.888888888889;
    case "zone_cooling_air_temperature_setpoint": return 23.888888888889;
    case "zone_heating_air_temperature_setpoint": return 20.555555555556;
    case "mixed_air_temperature": return 0.3 * oa + 0.7 * (22.222222222222 + 0.444444444444 * wave(i, 40)) + (sick ? 3.333333333333 * square(i, 90, 0.3) : 0);
    case "discharge_air_temperature": return sick ? 12.777777777778 + 5.555555555556 * wave(i, 70) + 2.222222222222 * wave(i, 7) : 12.777777777778 + 0.666666666667 * wave(i, 50);
    case "discharge_air_temperature_setpoint": return occ ? 12.777777777778 : 15.555555555556;
    case "air_handling_unit_discharge_air_temperature": return 12.777777777778 + 0.555555555556 * wave(i, 55);
    case "preheat_heating_coil_outlet_air_temperature": return 10 + 2.777777777778 * wave(i, 90);
    case "supply_fan_command": return occ ? (sick ? 80 : 65 + 20 * wave(i, 120)) : 0;
    case "supply_fan_speed_command": return occ ? (sick ? 80 : 65 + 20 * wave(i, 120)) : 0;
    case "occupancy_status": return occ ? 1 : 0;
    case "supply_fan_operating_status": {
      if (!occ) return sick && i % 288 > 40 && i % 288 < 70 ? 1 : 0; // running while the schedule says off
      return sick && i % 288 > 130 && i % 288 < 190 ? 0 : 1; // commanded on, proven off
    }
    case "damper_position_command": return occ ? (sick ? 10 : 20 + 70 * Math.abs(wave(i, 180))) : 0;
    case "damper_position": return occ ? (sick ? 10 : 20 + 68 * Math.abs(wave(i, 180))) : 0;
    case "outdoor_air_intake_damper_position_command": return occ ? (sick ? 10 : 15 + 80 * Math.abs(wave(i, 200))) : 0;
    case "discharge_air_static_pressure": return sick ? 149.304 + 49.768 * wave(i, 30) : 373.26 + 24.884 * wave(i, 45);
    case "discharge_air_static_pressure_setpoint": return 373.26;
    case "discharge_air_static_pressure_reset_request_count": return Math.round(3 * Math.abs(wave(i, 160)));
    case "cooling_valve_position_command": return sick ? 30 + 60 * Math.abs(wave(i, 110)) : (occ ? 40 * Math.abs(wave(i, 220)) : 0);
    case "heating_valve_position_command": return occ ? 30 * Math.max(0, wave(i, 260, 3)) : (sick ? 25 : 0);
    case "terminal_unit_heating_valve_position_command": return sick ? 70 * square(i, 96, 0.5) : 20 * Math.max(0, wave(i, 150));
    case "terminal_unit_discharge_air_temperature": return 14.444444444444 + 6.666666666667 * square(i, 80, 0.35);
    case "terminal_unit_inlet_air_temperature": return 12.777777777778 + 1.111111111111 * wave(i, 70);
    case "terminal_unit_discharge_air_total_volume_flow_rate": return 424.7523 + 188.7788 * wave(i, 100);
    case "discharge_air_volume_flow_rate": return sick ? 56.63364 + 14.15841 * wave(i, 90) : 117.98675 + 37.75576 * wave(i, 130);
    case "discharge_air_volume_flow_rate_minimum": return 70.79205;
    case "zone_air_co2": return 600 + 400 * Math.abs(wave(i, 140)) + (occ ? 150 : 0);
    case "cooling_coil_inlet_air_temperature": return 15.555555555556 + 1.666666666667 * wave(i, 50);
    case "cooling_coil_outlet_air_temperature": return 12.777777777778 + 1.111111111111 * wave(i, 50) + (sick ? 2.222222222222 : 0);
    case "heating_coil_inlet_air_temperature": return 12.777777777778 + 1.666666666667 * wave(i, 66);
    case "heating_coil_outlet_air_temperature": return 23.888888888889 + 2.222222222222 * wave(i, 66);
    case "supply_chilled_water_temperature": return 6.666666666667 + 1.111111111111 * wave(i, 95);
    case "return_chilled_water_temperature": return 11.111111111111 + 1.666666666667 * wave(i, 95, 0.4);
    case "supply_chilled_water_temperature_setpoint": return 6.666666666667;
    case "chilled_water_pressure_delta": return 68947.57 + 20684.271 * wave(i, 85);
    case "chilled_water_pressure_delta_setpoint": return 75842.327;
    case "chilled_water_volume_flow_rate": return 18.92706 + 7.570824 * wave(i, 120);
    case "chilled_water_reset_request_count": return Math.round(4 * Math.abs(wave(i, 210)));
    case "supply_hot_water_temperature": return 65.555555555556 + 6.666666666667 * wave(i, 130);
    case "return_hot_water_temperature": return 54.444444444444 + 4.444444444444 * wave(i, 130, 0.3);
    case "hot_water_reset_request_count": return Math.round(3 * Math.abs(wave(i, 190)));
    case "supply_condenser_water_temperature": return e === 0 ? null : 26.666666666667 + 2.222222222222 * wave(i, 100);
    case "electric_power": return 40 + 15 * wave(i, 288, 0.5);
    case "electric_energy": return (40 + 15 * wave(i, 288, 0.5)) * step / 3600;
    case "chiller_electric_current": case "chiller_electric_current": return 80 + 30 * wave(i, 100);
    case "chiller_electric_power": return 100 + 35 * wave(i, 100);
    case "return_air_relative_humidity": return 45 + 5 * wave(i, 80);
    case "zone_air_relative_humidity": return 48 + 8 * wave(i, 120);
    case "mixed_air_relative_humidity": return 50 + 5 * wave(i, 90);
    case "discharge_air_relative_humidity": return 70 + 5 * wave(i, 60);
    default:
      if (STATUS.has(col)) return square(i + (seed % 50), 60 + (seed % 90), 0.5 + (sick ? 0.2 : 0)) * (occ ? 1 : 0.0);
      if (PERCENT.has(col) || BOOLEAN_CMD.has(col)) return 50 + 45 * wave(i, 60 + (seed % 120), seed);
      if (HUMIDITY.has(col)) return 50 + 15 * wave(i, 90 + (seed % 50), seed);
      return 50 + 20 * wave(i, 97 + (seed % 60), seed % 7);
  }
}

function buildDataset(pack, { equipments = 2, days = 3, stepSeconds = 300, gaps = true, duplicateRole = true, plantSensors = false } = {}) {
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
          // occupancy_status: text tokens for unit 0, numeric strings (try_double path) for unit 1
          row[c.name] = e === 0 ? (occ ? "Occupied" : "Unoccupied") : (occ ? "1.0" : "0.0");
        } else {
          const v = signal(c.name, e, i, h, occ, stepSeconds);
          row[c.name] = v === null ? null : Math.round(v * 1e6) / 1e6;
        }
      }
      // sensor dropouts (NULL cells) on unit 0
      if (e === 0 && i % 97 === 5) { row.discharge_air_temperature = null; row.mixed_air_temperature = null; }
      history.push(row);
    }
  }
  const weather = [];
  for (let i = 0; i < steps; i += 4) { // every 20 min at 5 min history
    const ts = T0 + i * stepSeconds * 1000;
    const h = ((i * stepSeconds) / 3600) % 24;
    const oa = 8.888888888889 + 13.333333333333 * wave(h, 24, -2.2);
    weather.push({ ts, outdoor_air_intake_temperature: oa, weather_service_air_temperature: oa + 0.333333333333, weather_service_air_dew_point_temperature: oa - 6.111111111111 });
  }
  // The stress fixture uses the same canonical units declared by the hook after ingest.
  const sensorUnits = [["outdoor_air_intake_temperature", "°C"], ["mixed_air_temperature", "°C"], ["zone_air_temperature", "°C"], ["return_air_temperature", "°C"], ["discharge_air_temperature", "°C"],
    ["supply_chilled_water_temperature", "°C"], ["return_chilled_water_temperature", "°C"], ["supply_hot_water_temperature", "°C"], ["return_hot_water_temperature", "°C"],
    ["outdoor_air_intake_relative_humidity", "%"], ["return_air_relative_humidity", "%"], ["zone_air_relative_humidity", "%"], ["mixed_air_relative_humidity", "%"], ["discharge_air_relative_humidity", "%"], ["discharge_air_static_pressure", "Pa"]];
  // opt-in (default off keeps the stress/parity datasets unchanged): the plant sweep roles, all SI
  if (plantSensors) sensorUnits.push(["chilled_water_volume_flow_rate", "L/s"], ["chilled_water_pressure_delta", "Pa"], ["supply_condenser_water_temperature", "°C"], ["return_condenser_water_temperature", "°C"], ["chiller_electric_power", "kW"]);
  const authorizedSeries = [];
  const sensorHistory = [];
  const equipment = [];
  for (const id of equipmentIds) {
    equipment.push({ building_id: "site-1", equipment_id: id });
    for (const [role, unit] of sensorUnits) authorizedSeries.push({ site_id: "site-1", equipment_id: id, role, unit });
    const series = sensorUnits.map(([role, unit]) => ({ series_id: `series-${id}-${role}`, role, unit }));
    if (duplicateRole) series.push({ series_id: `series-${id}-discharge_air_temperature-duplicate`, role: "discharge_air_temperature", unit: "°C" });
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
  if (duplicateRole) authorizedSeries.push({ site_id: "site-1", equipment_id: equipmentIds[0], role: "discharge_air_temperature", unit: "°C" }); // duplicate role: excluded by the rule
  const utilityMonthly = [{ billing_period: "2026-01", electric_energy: 5000 }, { billing_period: "2026-02", electric_energy: 100 }];
  const utilityInterval = [];
  for (let i = 0; i < steps; i += 3) utilityInterval.push({ ts: T0 + i * stepSeconds * 1000, electric_energy: 3.3 + 1.2 * wave(i, 288) });
  return {
    historyColumns: histCols.map((c) => ({ name: c.name, type: c.type === "text" ? "text" : "double" })),
    history, weather, authorizedSeries, sensorHistory, equipment, utilityMonthly, utilityInterval,
  };
}

module.exports = { buildDataset };
