# Open-FDD SQL rules for PostgreSQL

This standalone adaptation contains all 77 registry SQL files from the local Open-FDD checkout, plus their tuning metadata. It targets PostgreSQL 14+ syntax, subject to execution qualification on your actual PostgreSQL version. Original equations and per-rule normalization were retained except for the documented dialect changes. Fault duration and confirmation use the forward timestamp delta. A gap longer than `MAX_GAP_HOURS` (default 1) is unknown: it is not fault time, not covered time, and it breaks the confirmation streak. The last sample does not add a trailing interval. No PostgreSQL server was available here. This is an implementation starting point, not a deployed FDD service or completed UI.

## Start here

- `rules/`: adapted PostgreSQL SQL templates, one per registry entry.
- `tuning_catalog.json`: complete labels, defaults, limits, steps, units, roles, equipment kinds and output columns; confirmation exposed as `confirm_min`, matching the Open-FDD UI.
- `registry.yaml`: original metadata, including source parity status.
- `render_rule.py`: standalone Python standard-library parameter renderer.
- `postgres_helpers.sql`: PostgreSQL safe numeric conversion helper used by occupancy rules.
- `input_contract.sql`: scratch wide input tables showing required column names and types; build views over your warehouse instead of copying this into production blindly.
- `tuning_storage.sql`: starter schema for configuration revisions and result provenance.
- `IMPLEMENTATION_PROMPT.md`: hand to your implementation agent along with this entire folder.
- `original_datafusion/` and `reference/`: originals and tuning/runtime reference code.
- `port_manifest.json`: source hashes, changed files and controls without SQL effects.
- `validation.json`: explicit verification scope and remaining limitations.

Render FC1 with a 5-minute sample grid and a 10-minute confirmation delay:

```powershell
python .\render_rule.py FC1 --poll-seconds 300 --params '{"eps_dsp":0.15,"confirm_min":10}'
```

The script prints SQL; it does not connect to your database. In an application import `render` and execute the returned SQL using a database driver. Parameters are validated finite numbers with registry limits. Template parameters are not native SQL bind variables. Data filters such as tenant/site/equipment/date must use driver bind variables, and relation names must come from an application allowlist. Don't accept user-authored SQL through this renderer.

## What changed

`CAST(... AS DOUBLE)` became `DOUBLE PRECISION`. PostgreSQL does not provide the DataFusion `TRY_CAST` syntax: occupancy rules call `fdd.try_double(text)`, returning NULL for invalid or overflowing numeric text. Numeric occupancy strings such as `0.0` still work, and textual tokens still use the original CASE branches.

`SV-RANGE` uses explicit comparisons to PostgreSQL floating-point NaN because PostgreSQL considers NaN equal to itself; the original `x != x` test is unsuitable there. For other rules, normalize nonfinite inputs to NULL before arithmetic, while retaining an invalid-value quality channel and raw NaN for SV-RANGE. Do not globally convert NaN to a healthy numeric value. Invalid sensor data must not create false comfort/economizer findings.

`UTIL-MONTHLY` uses UTC `YYYY-MM` keys instead of casting a truncated timestamp to text. Its `utility_monthly.billing_period` adapter must return the same `YYYY-MM` format. Sites that bill by local calendar month need a deliberately configured billing timezone in both adapters, with tests across month/DST boundaries.

## Input contract matters as much as dialect

Rules read wide relations named `history`, `weather`, `utility_interval`, and `utility_monthly`. Supply a consistently sampled grid with exactly one row per equipment per UTC timestamp. Timestamp is `timestamp with time zone`; analogs and status/command inputs are numeric, not PostgreSQL booleans; `occ_mode` is text. Missing optional columns need typed NULL projections. Missing required roles must produce a skipped/not-applicable result, not fabricated data.

Execute against **one authorized tenant and building at a time**. These SQL files partition by `equipment_id` alone and weather joins partition by timestamp. An unscoped warehouse view would mix sites that reuse equipment IDs and could attach another site's weather. Scope all four inputs before the rule query. Use transaction-local temporary views/tables or a validated CTE adapter with bound scope values. Select equipment by explicit metadata kind and mapped roles; IDs are exact keys, never prefix heuristics. Mixed equipment cadences need separate runs/resampling, not a single invented poll interval.

Temperatures and thresholds are predominantly Fahrenheit, flow CFM, static pressure inches water column. Read each role's unit contract. Convert absolute temperatures and temperature differences correctly (an offset applies only to absolute temperatures), including setpoints. Preserve each source rule's percent/fraction behavior: ECON-1/2 use a 1.5 cutoff while many other rules use >1.0. Do not silently standardize these inequalities during a port.

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

## Verification

All 77 templates render with defaults and bind/execute on empty DuckDB inputs using compatibility adapters for the PostgreSQL helper and month formatting. Seventy-six match their original DataFusion SQL on a small regular-grid DuckDB fixture. UTIL-MONTHLY is excluded from that comparison because of its changed month-key contract. These are preliminary checks, not execution on either PostgreSQL or DataFusion and not exhaustive rule accuracy tests. Run `verify_pack.py` with DuckDB installed to reproduce them. `postgres_smoke.sql` is a rollback-only scratch PostgreSQL binding/execution check generated by that script; run it in a disposable test database with `psql -v ON_ERROR_STOP=1 -f postgres_smoke.sql`. Qualify fault cases and tuning responsiveness before deployment.

Sources: [Open-FDD cookbook](https://bbartling.github.io/open-fdd/rules/cookbook/sql-cookbook.html), [PostgreSQL numeric types and NaN](https://www.postgresql.org/docs/current/datatype-numeric.html), [window functions](https://www.postgresql.org/docs/current/functions-window.html), [date/time functions](https://www.postgresql.org/docs/current/functions-datetime.html). Source license is included.
