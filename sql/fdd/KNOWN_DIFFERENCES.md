# Known differences and release blockers

## SV-RATE: equal hours, different fault timestamps

The independently authored raw fault window is 2026-01-07T11:05:00Z through 12:05:00Z, end exclusive: 12 samples, exactly 3,600 seconds. The real Open-FDD pandas oracle returns that window. Both SQL versions return 11:00:00Z through 12:00:00Z: also 12 samples and one hour, but two timestamps disagree.

This is not rounding noise. The source SQL checks two consecutive instantaneous exceedances. The pandas implementation uses a rolling median of instantaneous rates with a 15-minute horizon, fallback window rates, profile-specific thresholds, noise deadband, persistence, extreme-event handling and operating-state context. The portable SQL currently represents only a subset. `persistence_min` is advertised in the SQL registry but is not consumed by its template.

The strict suite deliberately fails SV-RATE for immediate and 15-minute confirmation, in both dialects. It has no xfail or relaxed tolerance. To close the blocker, port the actual profile algorithm and tuning effects to the target warehouse, or explicitly version the portable screening rule as a different algorithm. Do not change the expected timestamps to fit whichever output is convenient. With profile-equivalent behavior, retain the authored golden and add noise/transition/profile boundary fixtures. A source-faithful portable subset can remain separately documented, but cannot claim full Open-FDD pandas parity.

## Imported FC1 healthy baseline was not healthy under current rules

The old fixture held duct static at 1.2 against a 1.5 setpoint during ordinary fan-on hours. Current pandas/SQL use fan status for full-fan proof and therefore detect roughly 40 hours rather than the old one-hour expectation. The new fixture explicitly sets static equal to its setpoint outside the intended injection while preserving the one-hour injection and golden interval. This is a new fixture correction, not a changed expected value. The original ZIP remains byte-for-byte intact. `reports/initial_import_comparison.json` retains the original failure evidence.

## Default startup/mode behavior is not yet fully equivalent

Some SQL rules check fan-on stability, while pandas GL36 rules suppress faults after heat/cool/economizer mode changes. The raw synthetic contract explicitly sets `mode_delay_min=0` and `startup_delay_min=0` where exposed; confirmation is tested separately. Source UI/default tuner values are retained unchanged. Passing these controlled cases does not establish full default-mode or arbitrary-tuning parity. Implement and test the selected holdoff policy before shipping those controls as equivalent.

## Sensor sweeps: per-role scores and elapsed silence (#1555)

`SV-STALE`, `SV-FLATLINE`, `SV-RANGE`, and `SV-SPIKE` now score each declared sensor role independently and return `(equipment_id, sensor_role, fault_hours)`. A long gap is assigned to the role that stopped reporting: the first `max_silence_hours` uses sample-and-hold; the remaining interval is fault time. The trailing silence is measurable through the last equipment timestamp when peer histories continue. Roles with no valid sample are unknown. Stale and flatline windows use elapsed seconds, including the held sample that crosses the window cutoff, so irregular polling is not converted to an arbitrary row count. Their ordinary fault interval starts at the first observed sample after the tuned window is met; confirmation retains the existing sample-time semantics. Silence excess starts exactly at the tuned threshold. `max_silence_hours` has a 0.25 h minimum and step for all four rules; `stale_hours` also permits 0.25 h.

The operational gate still applies to ordinary flatline/range/spike evidence, but silence faults count even while de-energized. `SV-SPIKE` compares only consecutive samples within `max_silence_hours`, so a post-outage value jump is not also labeled a spike. The per-role fault-hour result and role-keyed timeline use the same split sample-hold segments; timeline confirmed seconds sum back to each role result.

## W4e SI-first sensor validation, weather, schedule and utility rules (#1284, #1439)

- SV-RATE is excluded from the `W4e_si_sensor_util` parity family. It stays unsupported on SI (see the SV-RATE section above) and is not claimed by W4e.
- Sensor-sweep tolerances (`flatline_tol`, `stale_tol`, `spike_limit`) and `oat_err` are temperature differences (K / delta degC), never absolute temperatures. Humidity roles use declared percent-RH literals (flatline 0.1, stale 0.05), not the temperature tolerance.
- SV-RANGE, SV-FLATLINE and SV-SPIKE SQL use the row-wise operational proof fallback order (fan status, fan command, VAV zone airflow, pump status, CHW pump command, chiller status); each row uses the first non-NULL proof, and rows with NULL values fall through to the next available proof. The airflow threshold is 23.597350 L/s (SI). The pandas oracle now uses the same row-wise fallback. Silence remains assessed independent of the gate.
- `authorized_series` must carry each role's SI unit (the NF app hook fills it from the point unit after converting to SI); without it the sensor sweep masks every value and records zero fault time.
- SCHED-1 comfort tuners are `comfort_low`/`comfort_high` (degC), matching the SI runner parameters.

## Oracle versions

The preparation host's installed `open-fdd` distribution is 4.4.1 (62 diagnostic rules). The copied local source snapshot declares 4.4.9 (71 rules). The installed-mode report has nine `ORACLE_UNAVAILABLE` entries for FCU rules, plus the SV-RATE failure. An absent oracle is never counted as pass. The source snapshot is explicitly selected; it is not represented as a downloaded/installed 4.4.9 release. Pin the actual published package available in your environment and rerun that mode.

## Other caveats

- The pack is executed by PGlite (real Postgres) and a translated SQLite in nf-app/tests/engines.test.mjs; a PostgreSQL server was not used.
- The six analytic/utility cases use authored numerical expectations; they are not diagnostic `open_fdd.rules.run_rule` twins.
- Three aggregate-only FCU rules do not implement configurable confirmation. The tests keep their confirmation at zero and the UI must label/disable unsupported controls.
- Utility fault-hours retain a fixed 720-hour proxy. This is not measured fault duration, including in the interval-MAE rule.
- The focused SV fixtures cover per-role isolation, long and trailing silence, de-energized silence, irregular 7-minute sampling and spike role attribution on both SQL engines. They are synthetic screening proofs, not field-data accuracy or every boundary value. The separate DataFusion and Timescale suites provide additional dialect/runtime qualification.
- Sensor-sweep tolerance metadata may span different physical quantities. Temperature display conversions are a convenience, not permission to apply Celsius offsets to humidity or pressure tolerances. Resolve per-role quantities explicitly for a warehouse UI.

## Percent / fraction contract (#1541)

Every command and position role is a fraction 0-1, every status is 0/1, and humidity is %RH 0-100, declared by `sql/fdd/input_contract.json` (`role_scales.json` is generated for compatibility). No SQL rule and no pandas rule guesses a scale by magnitude any more (the `> 1.0` / `>= 1.5` branches, `pid_hunt_1`'s reverse guess and the pandas `num <= 1.5` / series-level `auto` guesses are gone). The pandas oracle's `norm_cmd` is a plain pass-through for fractions; only RCx analytics (`open_fdd/analytics`) keeps a series-level guess, for legacy mixed-scale exports. Removing the element-wise (SQL) vs series-level (pandas) guesses also removed three parity divergences: AHU-SIMUL, CHW-2 and FCU-VALVE-PASS-CLG now match. A caller that feeds the SQL directly must supply fractions and 0/1.
