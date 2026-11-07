-- Scratch input contract only. Do not execute against production without designing adapters.
-- ALL INPUTS ARE SI: temperature degC, temperature differences delta-degC, pressure Pa (duct static too),
-- air/water flow L/s, power kW, energy kWh. Convert at ingest (nf-app/static/units.js toSI);
-- the rules never convert units and never guess them.
--
-- ONE DECLARED SCALE PER COLUMN (issue #1541). The columns are bare DOUBLE PRECISION, so the scale is part of the
-- contract. The machine-readable table is sql/fdd/role_scales.json (role -> scale); the rules never decide a scale by
-- magnitude (there is no "> 1 means percent" branch anywhere).
--   FRACTION 0-1 (1 = 100 %, 0.01 = 1 %):  fan_cmd, return_fan, chw_pump_cmd, cw_pump_cmd, tower_fan_cmd, chiller_cmd,
--     clg_valve_pct, htg_valve_pct, reheat_valve_pct, damper_pct, damper_cmd, oa_damper_pct.
--     (The "_pct" in a column name is historical: the value is a fraction. Thresholds such as FULL_OPEN_PCT 0.975 or
--     FAN_ON_MIN 0.01 are fractions too, unit "frac" in tuning_catalog.json.)
--   BOOLEAN 0/1 (an averaged bucket is an on-fraction in [0, 1]):  fan_status, chiller_status, chw_pump_status,
--     pump_status, compressor_status, loop_enabled, clg_available, building_zone_load_satisfied,
--     building_ahu_load_satisfied.
--   PERCENT RELATIVE HUMIDITY 0-100 (a physical quantity, not a command; SV-RANGE and the sensor sweep want %RH):
--     oa_h, ra_h, zone_rh, ma_h, sa_h, web_oa_h.
--   TEXT: occ_mode.
--   Everything else is physical SI (degC, Pa, L/s, kW, kWh, A, ppm, request counts); see role_scales.json "si:<unit>".
-- The ingest layer (nf-app/hooks/fdd.js siPlan, hooks/lib/timescale.js) brings each point to its role's scale from the
-- point's declared unit: "%" -> /100, ratio/fraction -> as is, no unit on a fraction role -> role skipped (the rules
-- that need it are not assessed). A caller that feeds the SQL directly must supply fractions and 0/1 itself.
CREATE TEMP TABLE history(equipment_id VARCHAR, timestamp_utc timestamp with time zone, "ahu_sat" DOUBLE PRECISION, "building_ahu_load_satisfied" DOUBLE PRECISION, "building_zone_load_satisfied" DOUBLE PRECISION, "chiller_amps" DOUBLE PRECISION, "chiller_cmd" DOUBLE PRECISION, "chiller_current" DOUBLE PRECISION, "chiller_power" DOUBLE PRECISION, "chiller_status" DOUBLE PRECISION, "chw_dp" DOUBLE PRECISION, "chw_dp_sp" DOUBLE PRECISION, "chw_flow" DOUBLE PRECISION, "chw_pump_cmd" DOUBLE PRECISION, "chw_pump_status" DOUBLE PRECISION, "chw_reset_request_sum" DOUBLE PRECISION, "chw_return_t" DOUBLE PRECISION, "chw_supply_sp" DOUBLE PRECISION, "chw_supply_t" DOUBLE PRECISION, "clg_available" DOUBLE PRECISION, "clg_valve_pct" DOUBLE PRECISION, "compressor_status" DOUBLE PRECISION, "cooling_coil_entering_temp" DOUBLE PRECISION, "cooling_coil_leaving_temp" DOUBLE PRECISION, "cooling_sp" DOUBLE PRECISION, "cw_supply_t" DOUBLE PRECISION, "damper_cmd" DOUBLE PRECISION, "damper_pct" DOUBLE PRECISION, "duct_static" DOUBLE PRECISION, "duct_static_sp" DOUBLE PRECISION, "electric_kw" DOUBLE PRECISION, "electric_kwh" DOUBLE PRECISION, "fan_cmd" DOUBLE PRECISION, "fan_status" DOUBLE PRECISION, "heating_coil_entering_temp" DOUBLE PRECISION, "heating_coil_leaving_temp" DOUBLE PRECISION, "heating_sp" DOUBLE PRECISION, "htg_valve_pct" DOUBLE PRECISION, "hw_reset_request_sum" DOUBLE PRECISION, "hw_return_t" DOUBLE PRECISION, "hw_supply_t" DOUBLE PRECISION, "kwh" DOUBLE PRECISION, "loop_enabled" DOUBLE PRECISION, "mat" DOUBLE PRECISION, "min_flow_sp" DOUBLE PRECISION, "oa_damper_pct" DOUBLE PRECISION, "oa_h" DOUBLE PRECISION, "oa_t" DOUBLE PRECISION, "occ_mode" VARCHAR, "preheat_leave_t" DOUBLE PRECISION, "pump_status" DOUBLE PRECISION, "rat" DOUBLE PRECISION, "reheat_valve_pct" DOUBLE PRECISION, "sat" DOUBLE PRECISION, "sat_sp" DOUBLE PRECISION, "static_reset_request" DOUBLE PRECISION, "tower_fan_cmd" DOUBLE PRECISION, "vav_discharge_t" DOUBLE PRECISION, "vav_inlet_t" DOUBLE PRECISION, "vav_total_flow" DOUBLE PRECISION, "web_oa_dp" DOUBLE PRECISION, "web_oa_t" DOUBLE PRECISION, "web_wb_t" DOUBLE PRECISION, "zone_air_temp_sp" DOUBLE PRECISION, "zone_co2" DOUBLE PRECISION, "zone_flow" DOUBLE PRECISION, "zone_t" DOUBLE PRECISION);
CREATE TEMP TABLE weather(timestamp_utc timestamp with time zone, oa_t double precision, web_oa_t double precision, web_oa_dp double precision);
CREATE TEMP TABLE utility_interval(timestamp_utc timestamp with time zone, kwh double precision);
CREATE TEMP TABLE utility_monthly(billing_period varchar, kwh double precision);
