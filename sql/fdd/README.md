# Open-FDD SQL rules for PostgreSQL

This standalone adaptation contains all 77 registry SQL files from the local Open-FDD checkout, plus their tuning metadata. It targets PostgreSQL 14+ syntax, subject to execution qualification on your actual PostgreSQL version. Original equations and per-rule normalization were retained except for the documented dialect changes. Most rules use forward timestamp deltas; a gap longer than `MAX_GAP_HOURS` (default 1) is unknown, not fault or covered time, and breaks confirmation. The four silence-based sensor sweeps (`SV-STALE`, `SV-FLATLINE`, `SV-RANGE`, `SV-SPIKE`) attribute silence beyond `max_silence_hours` (default 0.5 h) to the affected sensor. All five sensor sweeps, including `SV-RATE`, return per-series results. The last sample adds no trailing interval except for the four silence sweeps when another history row establishes the equipment observation end. This is an implementation starting point, not a deployed FDD service or completed UI.

## Start here

- `postgres/rules/`: adapted PostgreSQL SQL templates, one per registry entry.
- `tuning_catalog.json`: complete labels, defaults, limits, steps, units, roles, equipment kinds and output columns; confirmation exposed as `confirm_min`, matching the Open-FDD UI.
- `registry.yaml`: original metadata, including source parity status.
- `render_rule.py`: standalone Python standard-library parameter renderer.
- `postgres/postgres_helpers.sql`: the `fdd.*` helpers (safe numeric conversion for occupancy rules; SI-only sensor-sweep unit gate).
- `input_contract.json`: canonical engine-independent scratch contract for role scales, relation columns and SI types.
- `input_contract.sql`: generated standalone scratch DDL for every relation used by the rendered rules, including sensor-validation metadata. Build views over your warehouse instead of copying this into production blindly.
- `schema/core.sql`: the **shared core schema**: `fdd.point` (bound points with their SI scale), `fdd.rule_result` (one row per site, equipment, rule, subject and window) and `fdd.rule_config` (tuning revisions). The NF Timescale app installs it; downstream applications vendor it byte for byte (also shipped as `open_fdd/data/core.sql`) and expose their samples as the view `fdd.input_sample` declared under `sources` in `input_contract.json` (version 3). `schema/core.catalog.json` is the generated catalog Postgres reports for it; `scripts/nf/build_core_schema.py --check` guards the copies. `tuning_storage.sql` is now only a pointer to it.
- `port_manifest.json`: source hashes, changed files and controls without SQL effects.

Render FC1 with a 5-minute sample grid and a 10-minute confirmation delay:

```powershell
python .\render_rule.py FC1 --poll-seconds 300 --params '{"eps_dsp":0.15,"confirm_min":10}'
```

The script prints SQL; it does not connect to your database. In an application import `render` and execute the returned SQL using a database driver. Parameters are validated finite numbers with registry limits. Template parameters are not native SQL bind variables. Data filters such as tenant/site/equipment/date must use driver bind variables, and relation names must come from an application allowlist. Don't accept user-authored SQL through this renderer.

## What changed

`CAST(... AS DOUBLE)` became `DOUBLE PRECISION`. PostgreSQL has no `TRY_CAST` syntax: occupancy rules call `fdd.try_double(text)`, returning NULL for invalid or overflowing numeric text. Numeric occupancy strings such as `0.0` still work, and textual tokens still use the original CASE branches.

`SV-RANGE` uses explicit comparisons to PostgreSQL floating-point NaN because PostgreSQL considers NaN equal to itself; the original `x != x` test is unsuitable there. For other rules, normalize nonfinite inputs to NULL before arithmetic, while retaining an invalid-value quality channel and raw NaN for SV-RANGE. Do not globally convert NaN to a healthy numeric value. Invalid sensor data must not create false comfort/economizer findings.

`UTIL-MONTHLY` uses UTC `YYYY-MM` keys instead of casting a truncated timestamp to text. Its `utility_monthly.billing_period` adapter must return the same `YYYY-MM` format. Sites that bill by local calendar month need a deliberately configured billing timezone in both adapters, with tests across month/DST boundaries.

## Input contract matters as much as dialect

`input_contract.json` is the one source for declared role scales and the complete scratch schema. Generate the standalone DDL and the legacy `role_scales.json` compatibility view with `python scripts/nf/build_input_contract.py`; use `--check` in CI. The NF SQL pack builder reads the same source. The DDL includes `history`, the long-form `sensor_history`, `weather`, and both utility relations (contract version 2; the unused `authorized_series` / `equipment` relations were dropped, no rule reads them). `sensor_history` contains `(equipment_id, series_id, sensor_role, unit, timestamp_utc, value)`: one row per bound point sample, with `series_id` equal to the NF point UUID and `value` already in SI. Wide `history` remains the equipment proof and observed-end source for sweeps. Use a consistent timestamp grid when joining proof rows. Timestamp is `timestamp with time zone`; analogs and status/command inputs are numeric, not PostgreSQL booleans; `occ_mode` is text. Missing required roles must produce a skipped/not-applicable result, not fabricated data.

Execute against **one authorized tenant and building at a time**. Most rules partition by `equipment_id`; the five sensor sweeps partition sample windows by `(equipment_id, series_id)`, with `sensor_role` used for thresholds and output labels. Weather joins partition by timestamp. An unscoped warehouse view would mix sites that reuse equipment IDs and could attach another site's weather. Scope all inputs before the rule query. Use transaction-local temporary views/tables or a validated CTE adapter with bound scope values. Select equipment by explicit metadata kind and mapped roles; IDs are exact keys, never prefix heuristics. Mixed equipment cadences need separate runs/resampling, not a single invented poll interval.

## Sensor sweep result grain and silence

All five sensor sweeps return one row per assessable bound sensor series: `(equipment_id, series_id, sensor_role, fault_hours, covered_hours)`. The canonical per-sweep role lists are in `open_fdd/data/sensor_sweep_roles.json`; SQL rendering, the generated NF rule catalog, and the pandas oracle read the same lists. `zone_flow` is never a sweep target. `duct_static` is assessed only by SV-RANGE and SV-SPIKE. Other bound roles can still provide operating-state context to rules but do not create sensor result rows. Two bound points with the same assessable role remain separate results. `series_id` is the point UUID; `sensor_role` describes the point and selects its rule threshold. A separate series result prevents a healthy sensor from masking a faulty peer and lets callers identify the exact point. Each sample in `sensor_history` carries its own SI unit; unsupported units and invalid/mixed-unit samples are masked. An assessable series with no covered interval returns `fault_hours = NULL` and `covered_hours = 0`.

## Sensor sweep limits: one SI source (#1581)

Every per-role number the five sweeps use lives in `open_fdd/data/sensor_sweep_limits.json` (SI only: degC, delta-degC,
%RH, Pa, L/s, kW). `sql/fdd/render_rule.py` renders it into the `sv_*` rules (`{{SV_RANGE_BANDS}}`, `{{SV_SPIKE_BANDS}}`,
`{{SV_FLATLINE_TOL}}`, `{{SV_STALE_TOL}}`, `{{SV_RATE_THRESHOLD}}`) and the pandas sweeps read the same file through
`open_fdd.rules.sensor_sweep_catalog.load_role_limits()`. Which sweep assesses a role is still decided by
`sensor_sweep_roles.json`. An invalid limit (non-finite, `lo >= hi`, non-positive delta, unknown quantity, missing source,
an assessed role without a limits entry) is rejected when the file is loaded.

- `lo` / `hi`: SV-RANGE band. SQL renders centre +/- half-width times the existing `range_scale_*` tuner (temperature, humidity,
  pressure); flow and power have no scale tuner.
- `spike_delta`: SV-SPIKE sample-to-sample delta (a real consecutive-sample difference within `max_silence_hours`, not a rate).
- `flat_tol` / `stale_tol`: span tolerance. Empty on a temperature role means "follow the rule tuner" (`flatline_tol` 0.055556,
  `stale_tol` 0.027778 delta-degC); a value equal to that default also follows the tuner. Humidity roles carry their own %RH value.
- `rate_per_h`: SV-RATE threshold per hour (portable SQL rule only; see KNOWN_DIFFERENCES.md). Empty or equal to the default
  3.333333 follows the `steady_fault_per_hour` tuner.
- Window lengths (`flat_s` 3600, `stale_s` 7200) and the 5 minute confirmation are global defaults, recorded in the file's
  `defaults` block: the SQL window frames are one constant per rule, so they cannot vary per role.

Inventory (R range, S spike, F flatline, T stale, A rate). The 5.0.12 rows are the previous effective defaults moved
unchanged (imperial-derived bands, so the SI numbers look odd: for example outside air -60 to 130 degF). The 5.0.13 plant
rows are conservative gross-fault bands for owner review; they are not tuned to any site.

| Role | Unit | Sweeps | Range | Spike delta | Flat tol | Stale tol | Rate per h | Provenance |
|---|---|---|---|---|---|---|---|---|
| `outside-air-temp` | degC | R S F T A | -51.111111 to 54.444445 | 20 |  |  | 3.333333 | 5.0.12 default |
| `mixed-air-temp` | degC | R S F T A | -28.888889 to 43.333333 | 13.888889 |  |  | 3.333333 | 5.0.12 default |
| `zone-air-temp` | degC | R S F T A | 4.444444 to 37.777778 | 6.666667 |  |  | 3.333333 | 5.0.12 default |
| `return-air-temp` | degC | R S F T A | 4.444444 to 37.777778 | 6.666667 |  |  | 3.333333 | 5.0.12 default |
| `discharge-air-temp` | degC | R S F T A | -1.111111 to 65.555555 | 22.222222 |  |  | 3.333333 | 5.0.12 default |
| `chilled-water-supply-temp` | degC | R S F T . | -1.111111 to 26.666667 | 11.111111 |  |  |  | 5.0.12 default |
| `chilled-water-return-temp` | degC | R S F T . | -1.111111 to 32.222223 | 11.111111 |  |  |  | 5.0.12 default |
| `hot-water-supply-temp` | degC | R S F T . | 4.444444 to 104.44444 | 33.333333 |  |  |  | 5.0.12 default |
| `hot-water-return-temp` | degC | R S F T . | 4.444444 to 104.44444 | 33.333333 |  |  |  | 5.0.12 default |
| `outside-air-humidity` | %RH | R S F T . | 0 to 100 | 25 | 0.1 | 0.05 |  | 5.0.12 default |
| `return-air-humidity` | %RH | R . F T . | 0 to 100 |  | 0.1 | 0.05 |  | 5.0.12 default |
| `zone-air-humidity` | %RH | R . F T . | 0 to 100 |  | 0.1 | 0.05 |  | 5.0.12 default |
| `mixed-air-humidity` | %RH | R . F T . | 0 to 100 |  | 0.1 | 0.05 |  | 5.0.12 default |
| `supply-air-humidity` | %RH | R . F T . | 0 to 100 |  | 0.1 | 0.05 |  | 5.0.12 default |
| `duct-static-pressure` | Pa | R S . . . | -248.84 to 1990.72 | 497.68 |  |  |  | 5.0.12 default |
| `chw-flow` | L/s | R . . . . | -1 to 1500 |  |  |  |  | 5.0.13 plant default |
| `chw-diff-pressure` | Pa | R . . . . | -6894.76 to 689475.73 |  |  |  |  | 5.0.13 plant default |
| `condenser-water-supply-temp` | degC | R S . . . | 0 to 50 | 11.111111 |  |  |  | 5.0.13 plant default |
| `condenser-water-return-temp` | degC | R S . . . | 0 to 55 | 11.111111 |  |  |  | 5.0.13 plant default |
| `chiller-power` | kW | R . . . . | -1 to 10000 |  |  |  |  | 5.0.13 plant default |

Plant roles are assessed by SV-RANGE (all five) and SV-SPIKE (condenser-water temperatures only). Flow, differential pressure
and power are not flatline/stale targets because they rest at a constant when the plant is off. Their unit gate is exact: only
`L/s`, `Pa` and `kW` are assessed; anything else is skipped, never converted. `chw-diff-pressure` uses the `air_pressure`
quantity of the SQL helpers (declared `Pa`).

`max_silence_hours` is available on the four silence sweeps (minimum and step 0.25 h). Gaps at or below the threshold use sample-and-hold. When a sensor has a next observation after a longer gap, the interval after the threshold is fault time for that series. If the point stops reporting while equipment rows continue, its final gap is measured through the equipment's last timestamp. A series with no valid observation is unknown. `SV-STALE` and `SV-FLATLINE` use elapsed-time trailing windows; their minimum window is 0.25 h. Numeric `RANGE` frames and the cutoff-crossing held sample keep the window tied to elapsed time on PostgreSQL, SQLite and TimescaleDB instead of a row count. `SV-RATE` retains its portable screening equation but evaluates consecutive samples, confirmation, coverage, and output independently for each sensor UUID.

## Units: SI only

Every input and every tuning value is SI: temperature degC, temperature differences delta-degC (no offset), pressure Pa (duct static included), flow L/s, power kW, energy kWh. Command and position roles are fractions 0-1, statuses are 0/1 and humidity is %RH 0-100 (next section). The rules never convert units and never guess a scale. Convert at ingest (the NF hook runs `nf-app/static/units.js toSI` on every history value) and convert back to the user's display system only in the UI. Sensor-sweep rules (SV-*) assess a series only when its declared unit is the SI unit of its quantity (degC, %, Pa); otherwise the series is masked, not converted. Thresholds were converted from the earlier imperial defaults without re-tuning (65 F = 18.333 degC, 10 delta-F = 5.556 delta-degC, 0.25 in.w.c. = 62.21 Pa, 1 cfm = 0.471947 L/s). Setpoints are inputs in the same SI units.

Weather must be selected for the same site and aligned to the input grid with an explicit maximum age. Do not use unlimited forward filling. Utility inputs require a meter/aggregation mapping; summing all equipment meters can double-count master/submeters. Distinguish interval kWh from cumulative meter totals and from average kW. Exact utility joins require aligned intervals.

## Retaining rule tuning

Use the catalog to build per-rule controls; preserve parameter keys, labels, limits, steps, units, aliases and reset defaults. Save effective overrides at tenant/site/rule scope, optionally equipment scope. Store immutable revisions and audit changes. A run/preview and its chart must use the same effective configuration, rule version and sample interval. After save, refresh both aggregate results and fault overlays; invalidate caches by configuration hash, not only time range.

`confirm_min` is converted to seconds. A sample is confirmed when the eligible forward hold accumulated inside the current raw-fault streak reaches `CONFIRM_SECONDS`. Confirmation 0 confirms immediately. Unconfirmed prefix time stays in the covered denominator and is not fault time. `CONFIRM_ROWS` remains available for row-framed detection windows; duration does not multiply a row count by `POLL_SECONDS`. `POLL_SECONDS` still sizes those row windows.

Hour windows become `ceil(hours * 3600 / poll_seconds)` rows; preceding bound is rows minus one. The fixed-flow window uses at least six rows, and its minimum-period count is `max(3, rows // 2)`. Startup delay can raise the mode delay. Explicit legacy `mix_tol` maps to per-sensor epsilons unless individually overridden; `supply_tol` maps to SAT epsilon. The supplied renderer makes those masters effective when explicitly supplied; qualify this behavior against the deployed application's effective parameter resolution because historical Rust ordering contains ambiguities.

The catalog marks `effect_in_sql: false` where a control has no supported effect in the template (including some confirmation controls). Keep its metadata for compatibility, but label it informational/unsupported and disable saving an ineffective override until behavior is implemented and tested. Do not promise that every slider changes every rule. AVG-ZONE-TEMP comfort-band controls, for example, are reference values rather than predicates. Confirmation is irrelevant to basic analytic outputs and is not implemented in several aggregate-only rules.

`UTIL-MONTHLY` and `UTIL-INTERVAL` retain the original 720-hour proxy. It is not measured elapsed fault time, and UTIL-INTERVAL is a whole-query MAE despite the source's rolling label. Label those outputs clearly as proxies; adding true billing/interval fault duration is a separate, tested semantic improvement. FCU and other source entries labeled `sql_screening` remain screening, not newly proven diagnostic parity.

Raw fault, confirmed fault, eligibility, skipped reason, coverage and measured signal/threshold values belong in UI detail outputs. Most shipped queries return only aggregates. An implementation must expose the intermediate masks and gate decisions from the same CTE pipeline and final coverage policy; aggregate-only files cannot alone reproduce the Open-FDD chart experience.

## Gaps, warmup and aggregation

Duration is the forward delta between samples. Duplicate timestamps contribute 0 and do not break a streak. A gap longer than one hour contributes 0 and breaks the streak, so an outage is unknown rather than fault or ok. The same one-hour fault on a regular 1, 5, or 15 minute grid agrees exactly when confirmation is immediate, because each grid covers the same 60 minutes and the last sample adds nothing. With a fixed confirmation delay the grids may differ by one sample of the coarsest cadence (15 minutes): a 10 minute confirm on 1 minute data credits 51 minutes of a 60 minute fault, and the same window at 15 minutes credits the whole hour once the first 15 minute interval crosses 10 minutes. Nine minutes of 1 minute fault with a 10 minute confirm credits nothing. Fault hours are never larger than covered hours, and covered hours are never larger than the first-to-last span. `POLL_SECONDS` is not a duration quantum. Null handling in some source rules allows operational proof to default to on; preserve and display that policy rather than claiming missing operational data always gates off.

For incremental runs, load sufficient pre-window history for rolling windows, startup and confirmation; calculate masks first, then aggregate only the requested report interval. Avoid counting warmup rows as report hours. If faults can span arbitrary boundaries, carry streak state or load from an established reset point. The supplied templates aggregate their full input; an agent must add reporting-window boundaries to detail/aggregate outputs before using warmup in production.

## Other SQL databases

The equations can be ported to SQL engines with CTEs, window functions and adequate numeric/date functions. They cannot run unchanged on every SQL database. Implement a dialect adapter for safe casts, double types, NaN/invalid values, text conversion, month/timezone functions, window bounds and statistical aggregates. PostgreSQL `IS DISTINCT FROM`, PL/pgSQL helpers and `to_char` are not universal. MySQL 8, SQL Server, BigQuery, Snowflake, Redshift and SQLite need their own execution and numerical tests; SQLite also needs a strategy for sample standard deviation. Keep tuning metadata and fixtures shared across dialects.

## Input contract: one declared scale per column (#1541)

The `history` columns are bare `DOUBLE PRECISION`, so a stored `1` could mean 1 % or full scale, and the rules used to guess by magnitude (`> 1.0` / `>= 1.5` meant percent, `pid_hunt_1` guessed the other way). That guess was wrong exactly at the boundary. Every column now has ONE declared scale, and no rule guesses:

| Scale | Roles | Meaning |
|---|---|---|
| `fraction` | `fan_cmd`, `return_fan`, `chw_pump_cmd`, `cw_pump_cmd`, `tower_fan_cmd`, `chiller_cmd`, `clg_valve_pct`, `htg_valve_pct`, `reheat_valve_pct`, `damper_pct`, `damper_cmd`, `oa_damper_pct` | 0-1; 1 is 100 %, 0.01 is 1 %. The `_pct` in a name is historical |
| `boolean` | `fan_status`, `chiller_status`, `chw_pump_status`, `pump_status`, `compressor_status`, `loop_enabled`, `clg_available`, `building_zone_load_satisfied`, `building_ahu_load_satisfied` | 0 or 1 (a resampled bucket is the on-fraction in [0, 1]) |
| `percent_rh` | `oa_h`, `ra_h`, `zone_rh`, `ma_h`, `sa_h`, `web_oa_h` | relative humidity 0-100: a physical quantity, not a command (SV-RANGE and the sensor sweep are %RH) |
| `text` | `occ_mode` | categorical string |
| `si:<unit>` | every other role: temperatures `si:degC`, `duct_static`/`chw_dp` `si:Pa`, flows `si:L/s`, `electric_kw`/`chiller_power` `si:kW`, `kwh` `si:kWh`, `chiller_amps`/`chiller_current` `si:A`, `zone_co2` `si:ppm`, `*_request_sum` `si:count` | physical SI, unchanged |

The role scales live in `input_contract.json`; `role_scales.json` is a generated compatibility view for existing tooling, and `input_contract.sql` is generated from the same declarations. `scripts/nf/build_rule_catalog.py` copies each scale into `nf-app/static/fdd-catalog.json` as `roles.<role>.scale` and fails when a role has none, so the hook, the docs and the Timescale path use the canonical declaration.

**Ingest rule** (`siPlan` in `nf-app/hooks/fdd.js`; `hooks/lib/timescale.js` applies exactly its decisions, it never decides itself). Decided per role from the point's declared unit and kind:

- `fraction`: unit `%`/`percent` -> divide by 100. Unit `ratio`/`fraction`/`0-1` -> as is. Kind Bool -> as is (0/1 is a valid fraction). **No unit (or an unrelated unit) -> the role is skipped and logged once per point, never guessed**; a rule that requires it is not assessed (no result is written, a previously published result goes stale). BACnet analog outputs normally carry the percent unit.
- `boolean`: kind Bool -> as is. Number/Enum: a `%` unit is divided by 100 first. The value must then lie in [0, 1]; a value outside it (a 0-100 analog, an enum 1/2/3) is **rejected** (not thresholded at 0.5, not rescaled) and the sample is treated as missing. Thresholding would turn a 0.4 on-fraction bucket into "off" and a 3-state enum into data it is not.
- `percent_rh`, `si:<unit>`, `text`: the existing SI conversion by unit (`units.js toSI`); temperature/pressure/flow roles with a missing or foreign unit are skipped.

A caller that feeds the SQL directly (a warehouse view, the pandas oracle, the parity harness, `synthetic_dataset.js`) must supply fractions and 0/1 itself.

**Thresholds** that are commands or positions are fractions too (`tuning_catalog.json` unit `frac`: `FULL_OPEN_PCT` 0.975, `ECON1_DAMPER_MAX` 0.05, `FAN_ON_MIN` 0.01, `PUMP_HI` 0.87, `REHEAT_PCT` 0.25, ...). `*_pct` parameters with unit `pct` are percent points of something that is not a command (coverage, OA fraction from temperatures `OA_MIN_PCT`, PID-HUNT span/deadband/variation).

**PID-HUNT-1** measures the control output in percent points because its span, deadband and total-variation parameters are percent points. It now converts the fraction to points once (`fraction * 100`) at the top of the rule. Before, a stored `1` stayed 1 point while `0.99` became 99 points, so a 0 <-> 1 % wiggle looked like a full-stroke swing.

## Verification

Every template is executed on PGlite (real PostgreSQL) and on the translated SQLite pack, and each rule that has a pandas twin is compared with it over a deterministic SI dataset: see `tests/parity/stress.py` (`--equips N --days N`; it fails on any unlisted divergence) and `docs/rules/parity.md`. These are synthetic screening checks, not field-data accuracy tests. Qualify fault cases and tuning responsiveness before deployment.

Sources: [Open-FDD rule catalog](https://bbartling.github.io/open-fdd/fdd-rules.html), [PostgreSQL numeric types and NaN](https://www.postgresql.org/docs/current/datatype-numeric.html), [window functions](https://www.postgresql.org/docs/current/functions-window.html), [date/time functions](https://www.postgresql.org/docs/current/functions-datetime.html). Source license is included.
