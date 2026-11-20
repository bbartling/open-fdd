# Known differences and release blockers

## SV-RATE: equal hours, different fault timestamps

The independently authored raw fault window is 2026-01-07T11:05:00Z through 12:05:00Z, end exclusive: 12 samples, exactly 3,600 seconds. The real Open-FDD pandas oracle returns that window. Both SQL versions return 11:00:00Z through 12:00:00Z: also 12 samples and one hour, but two timestamps disagree.

This is not rounding noise. The source SQL checks two consecutive instantaneous exceedances. The pandas implementation uses a rolling median of instantaneous rates with a 15-minute horizon, fallback window rates, profile-specific thresholds, noise deadband, persistence, extreme-event handling and operating-state context. The portable SQL currently represents only a subset. `persistence_min` is advertised in the SQL registry but is not consumed by its template.

The strict suite deliberately fails SV-RATE for immediate and 15-minute confirmation, in both dialects. It has no xfail or relaxed tolerance. To close the blocker, port the actual profile algorithm and tuning effects to the target warehouse, or explicitly version the portable screening rule as a different algorithm. Do not change the expected timestamps to fit whichever output is convenient. With profile-equivalent behavior, retain the authored golden and add noise/transition/profile boundary fixtures. A source-faithful portable subset can remain separately documented, but cannot claim full Open-FDD pandas parity.

## SV-RATE: portable screening rule versus the context-aware pandas profile algorithm (decision, #1581)

The SQL SV-RATE stays the portable screening rule: one sample-to-sample rate per hour, a generic `rate_per_h` threshold
(`open_fdd/data/sensor_sweep_limits.json`, default 3.333333 delta-degC/h for the five air-temperature roles), a 1 h gap
limit and a 10 min confirmation. The pandas `sensor_rate` profile library (per-role steady/transient thresholds, rolling
median, noise deadband, operating-state context) is a different, richer algorithm. They are deliberately not forced to agree:
SV-RATE remains in `KNOWN_DIVERGENT` and the section above still applies. Only the SQL side reads `rate_per_h`; the pandas
profile numbers are unchanged. Porting the profile algorithm to SQL is a separate decision, not part of the limits source.

## Stress-only differences: TRIM-3 and VAV-REHEAT (#1582)

`python tests/parity/stress.py --equips 8 --days 7` compares 71 pandas twins; the 2x3 pytest dataset never reaches the
branches below, so these two are pinned in `STRESS_ONLY_DIVERGENT` (tests/parity/test_parity.py), not in `KNOWN_DIVERGENT`.

- **VAV-REHEAT** (SQL 16.0833 h, pandas 15.9167 h on one equipment): pandas runs the rule behind the operational gate
  `fan_running` with `startup_delay_seconds=600`; SQL has no startup holdoff. A standing fault at fan start is confirmed one
  5-minute sample earlier in SQL at each of the two fan starts in the 7-day run (0.1667 h in total). With the holdoff removed
  pandas equals SQL (regression test `test_vav_reheat_difference_is_exactly_the_startup_holdoff`). Same family as VAV-AHU-LEAVE,
  OA-1 and CHW-1 ("Default startup/mode behavior is not yet fully equivalent" above). VAV-6 was a different cause
  (the pandas frame never mapped `clg_available`) and matches since #1642.
- **TRIM-3** (SQL 1.5 h, pandas skipped on every equipment): three separate differences. (1) pandas reads the role
  `hw-reset-request-sum`; the SQL contract and the NF role are `hot-water-reset-request-sum` (the same applies to TRIM-4 and
  `chw-reset-request-sum` / `chilled-water-reset-request-sum`), so with contract names pandas has no input and returns
  `SKIPPED_MISSING_ROLES`. (2) With the pandas name supplied, SQL faults when the request sum is `<=` `request_lo` and pandas
  when it is `<` `request_lo` (the synthetic request sum takes the value 1 = `request_lo` on 78 of 384 hot samples). (3) pandas adds
  the hydronic-flow gate with a 600 s startup holdoff. With the pandas name supplied the two still differ (SQL 1.5 h against
  pandas 0.4167 h). Not changed here: aligning the names and the comparison changes public pandas roles and rule semantics and
  needs an owner decision; see the follow-up on #1582.

## Imported FC1 healthy baseline was not healthy under current rules

The old fixture held duct static at 1.2 against a 1.5 setpoint during ordinary fan-on hours. Current pandas/SQL use fan status for full-fan proof and therefore detect roughly 40 hours rather than the old one-hour expectation. The new fixture explicitly sets static equal to its setpoint outside the intended injection while preserving the one-hour injection and golden interval. This is a new fixture correction, not a changed expected value. The original ZIP remains byte-for-byte intact. `reports/initial_import_comparison.json` retains the original failure evidence.

## Default startup/mode behavior is not yet fully equivalent

Some SQL rules check fan-on stability, while pandas GL36 rules suppress faults after heat/cool/economizer mode changes. The raw synthetic contract explicitly sets `mode_delay_min=0` and `startup_delay_min=0` where exposed; confirmation is tested separately. Source UI/default tuner values are retained unchanged. Passing these controlled cases does not establish full default-mode or arbitrary-tuning parity. Implement and test the selected holdoff policy before shipping those controls as equivalent.

## Sensor sweeps: per-series scores and elapsed silence (#1555, #1565)

All five sensor sweeps score each assessable bound point independently and return `(equipment_id, series_id, sensor_role, fault_hours, covered_hours)`. The shared allowlists in `open_fdd/data/sensor_sweep_roles.json` are consumed by SQL rendering, the generated NF catalog, and the pandas oracle. `zone_flow` is not a sweep target; `duct_static` is assessed only by RANGE and SPIKE. `series_id` is the NF point UUID, so points with duplicate roles do not collapse together. An assessable series with no covered interval has `fault_hours = NULL` and `covered_hours = 0`, preserving the NF `null` result in Timescale. Missing data is scored once, by `SV-STALE` (#1673): a gap longer than `stale_after_hours` (through the requested window end, or the last equipment timestamp) is stale time for the series that stopped reporting, with or without run proof, and a bound series with no sample is stale for the whole window. `SV-FLATLINE`, `SV-RANGE` and `SV-SPIKE` hold a sample for at most `max_silence_hours`; the rest of the gap is unknown for them. Flatline windows use elapsed seconds, including the held sample that crosses the window cutoff, so irregular polling is not converted to an arbitrary row count. Their ordinary fault interval starts at the first observed sample after the tuned window is met; confirmation retains the existing sample-time semantics. Stale time starts exactly at the tuned threshold. `max_silence_hours` and `stale_after_hours` have a 0.25 h minimum and step.

Existing 5.0.10 result points for roles outside a sweep's allowlist may remain in NF history. New runs stop publishing result values and timelines for those excluded roles; history is not deleted automatically.

The operational gate applies to flatline/range/spike evidence; SV-STALE is not gated. The pandas runner gives the sweeps the stored SI values before quality normalization, as SQL does, so an out-of-range value is a range fault, not a gap (#1673). `SV-SPIKE` compares only consecutive samples within `max_silence_hours`, so a post-outage value jump is not also labeled a spike. Sample windows partition by `(equipment_id, series_id)`; role only selects a threshold and labels output. Timelines carry both identifiers and use the same split sample-hold segments; confirmed seconds sum back to each series result. `SV-RATE` now emits fault and coverage hours for each input point, including a zero-coverage row when that rule does not assess a series.

## W4e SI-first sensor validation, weather, schedule and utility rules (#1284, #1439)

- SV-RATE is excluded from the `W4e_si_sensor_util` parity family. It stays unsupported on SI (see the SV-RATE section above) and is not claimed by W4e.
- Sensor-sweep tolerances (`flatline_tol`, `spike_limit`) and `oat_err` are temperature differences (K / delta degC), never absolute temperatures. Humidity roles use declared percent-RH literals (flatline 0.1), not the temperature tolerance. `stale_tol` is retired (#1673).
- SV-RANGE, SV-FLATLINE and SV-SPIKE SQL use the row-wise operational proof fallback order (fan status, fan command, VAV zone airflow, pump status, CHW pump command, chiller status); each row uses the first non-NULL proof, and rows with NULL values fall through to the next available proof. The airflow threshold is 23.597350 L/s (SI). The pandas oracle now uses the same row-wise fallback. Missing data (SV-STALE) is assessed independent of the gate.
- Sweep proof alignment (#1631): a long-form sensor sample takes the proof of the latest `history` row of its equipment at or before it, held for at most `MAX_GAP_HOURS` (default 1 h). No such row, an older one, or a NULL proof is unknown: with the gate on it cannot create a fault (it used to count as energized through `COALESCE(..., 1)` on an exact timestamp join, so sensor samples 60 s off the proof grid turned a proven-OFF day into 23.9 fault hours). Equipment with sensor history but no `history` row is `no_run_proof` with the gate on. Sensor-data coverage (`covered_hours`) is unchanged. The pandas reference shares one index for proof and sensor values, the aligned case of the same rule; the SPARQL client's exact join is the same rule with a zero hold (fail-closed).
- Each `sensor_history` row carries the source unit and its SI value. The SQL checks the row's unit against the role quantity; a non-SI or unsupported unit is masked and breaks that series' continuity.
- SCHED-1 comfort tuners are `comfort_low`/`comfort_high` (degC), matching the SI runner parameters.

## Oracle versions

The preparation host's installed `open-fdd` distribution is 4.4.1 (62 diagnostic rules). The copied local source snapshot declares 4.4.9 (71 rules). The installed-mode report has nine `ORACLE_UNAVAILABLE` entries for FCU rules, plus the SV-RATE failure. An absent oracle is never counted as pass. The source snapshot is explicitly selected; it is not represented as a downloaded/installed 4.4.9 release. Pin the actual published package available in your environment and rerun that mode.

## Other caveats

- The pack is executed by PGlite (real Postgres) and a translated SQLite in nf-app/tests/engines.test.mjs; a PostgreSQL server was not used.
- The six analytic/utility cases use authored numerical expectations; they are not diagnostic `open_fdd.rules.run_rule` twins.
- Three aggregate-only FCU rules do not implement configurable confirmation. The tests keep their confirmation at zero and the UI must label/disable unsupported controls.
- Utility fault-hours retain a fixed 720-hour proxy. This is not measured fault duration, including in the interval-MAE rule.
- The focused SV fixtures cover per-role isolation, long and trailing silence (SV-STALE only), de-energized silence, expected series with no sample (`nf-app/tests/sv-stale-gap.test.mjs`), irregular 7-minute sampling and spike role attribution on both SQL engines. They are synthetic screening proofs, not field-data accuracy or every boundary value. The separate Timescale suite provides additional dialect/runtime qualification.
- Sensor-sweep tolerance metadata may span different physical quantities. Temperature display conversions are a convenience, not permission to apply Celsius offsets to humidity or pressure tolerances. Resolve per-role quantities explicitly for a warehouse UI.

## fault_pct denominators (#1631, #1723)

Resolved in 5.0.21. Run-proof gated rules divide `fault_hours` by proven-on time in both engines: SQL `active_hours` (held
time while the resolved run proof is on, or every held sample when the gate is off) and pandas `finalize_result(pct_mask=...)`
(the run-proof mask, or every sample when the gate is off), reported as `metrics["active_hours"]`. Each rule's own gate
still decides which samples can fault, so `fault_hours` is unchanged. The parity verdict compares the two denominators
and fails on a difference beyond `Policy.active_tol_h` (1 h); a rule pandas did not assess (SKIPPED) is not compared.
Basic 4x3 and 8x7 and edge 4x3: 0 pairs.

## Run proof from an analog command with no unit (#1631)

The NF hooks' run-proof resolver (`nf-app/static/run-proof.js`) skips an equipment's numeric **analog** command (speed,
VFD, position, ...) with no percent or 0-1 fraction unit as a proof candidate, because its 0-100 or 0-1 scale cannot be
told apart against the 0-1 proof threshold; the next candidate (another own command, then a feeder) wins. Start/stop
(run / enable) commands stay usable as 0/1 even with no unit or `kind`. pandas frames are SI without point units, so
`open_fdd.run_proof` keeps such a command; the parity datasets bind the resolved proof as a column, so the engines matrix
is not affected.

## Percent / fraction contract (#1541)

Every command and position role is a fraction 0-1, every status is 0/1, and humidity is %RH 0-100, declared by `sql/fdd/input_contract.json` (`role_scales.json` is generated for compatibility). No SQL rule and no pandas rule guesses a scale by magnitude any more (the `> 1.0` / `>= 1.5` branches, `pid_hunt_1`'s reverse guess and the pandas `num <= 1.5` / series-level `auto` guesses are gone). The pandas oracle's `norm_cmd` is a plain pass-through for fractions; only RCx analytics (`open_fdd/analytics`) keeps a series-level guess, for legacy mixed-scale exports. Removing the element-wise (SQL) vs series-level (pandas) guesses also removed three parity divergences: AHU-SIMUL, CHW-2 and FCU-VALVE-PASS-CLG now match. A caller that feeds the SQL directly must supply fractions and 0/1.
