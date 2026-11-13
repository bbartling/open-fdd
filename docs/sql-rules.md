---
title: Writing SQL rules
parent: Rules
nav_order: 6
---

# Writing SQL rules

PostgreSQL is the production FDD source. The SQLite pack is generated from it for smaller NF hosts. Keep every rule
site-neutral and use SI values at the rule boundary.

## Choose your rule workflow

| Goal | Start here |
|---|---|
| Extend a shipped rule or add a new SQL fault rule | Follow the source, registry, build, and test steps below |
| Run existing SQL in another application | [Using SQL rules outside Open-FDD](rules/borrowing-sql.html) |
| Execute SQL in DuckDB and independently compare fault hours to pandas | [Runnable DuckDB tutorial](https://github.com/bbartling/open-fdd/tree/master/tutorials/duckdb_sql_parity) |
| Understand which rules have matching pandas equivalents | [Parity catalog](rules/parity.html) and [parity harness](rules/parity-harness.html) |

A **SQL-only rule is supported** (not every shipped SQL rule has a pandas twin), but do not label a new rule as parity-verified unless its independent pandas implementation exists and passes tests. The DuckDB example currently proves FC1, FC2, and CMD-1 on its seeded basic data; it does **not** mean every PostgreSQL rule executes unmodified in DuckDB.

## Where inputs and results live

Rules read per-run scratch tables (`history`, `weather`, ...) built from the input contract. In the Full edition the
scratch `history` is built from the view `fdd.input_sample(site_id, point_key, ts, value)` (SI values) joined to
`fdd.point`, and results are upserted into `fdd.rule_result`; tuning revisions live in `fdd.rule_config` (the Full edition's Tuning tab
stores per-site and per-equipment sensor-sweep limits there in SI, rule id `SV-LIMITS`). All
three tables are in `sql/fdd/schema/core.sql`, which every application using Open-FDD shares byte for byte. An
application provides only its own `fdd.input_sample` view with the signature declared under `sources` in
`sql/fdd/input_contract.json`.

## Rule contract

The FDD engine loads a scoped, typed `history` table with one equipment and timestamp per row and one SI column per
role. `weather` contains as-of weather data. `equipment` contains model and operational context. A rule query receives
those tables and its tuned parameters, then returns one row per equipment with its `equipment_id` and declared output
columns. Sensor sweeps use the long-form sensor relation and return one row per assessed sensor series.

Rules must not read NF tables directly, perform unit conversion, or infer scales from values. Missing, unknown, or
unusable input remains unknown. Do not convert it to a healthy zero. Keep operational gates and coverage
requirements explicit in the SQL.

## Add or change a rule

1. Edit or add `sql/fdd/postgres/rules/<rule>.sql`.
2. Declare the rule, equipment kinds, required and optional roles, parameters, units, confirmation time, and output
   columns in `sql/fdd/registry.yaml` and `sql/fdd/tuning_catalog.json`.
3. Add any new canonical role in `sql/fdd/role_map.json` and its scale/type in `sql/fdd/input_contract.json`.
4. Render the rule and build the catalog and both packs with these commands.

   ```bash
   python3 scripts/nf/build_rule_catalog.py
   python3 scripts/nf/build_sql_pack.py
   python3 scripts/nf/gen_rule_docs.py
   python3 scripts/nf/gen_cookbook.py
   ```

5. Add a deterministic fixture that exercises the fault and healthy path. If you want a pandas twin, implement the corresponding independent rule under `open_fdd/rules/` and register it; do not reuse the SQL output as the pandas oracle. Check output columns, missing-data behavior,
   confirmation edges, operational gating, and relevant timeline rows.
6. Run the focused engine and parity tests below. Document a deliberate difference in
   `sql/fdd/KNOWN_DIFFERENCES.md` and the parity registry.

## Roles and units

Use the canonical role names in `role_map.json`. Equipment kinds restrict where a rule runs. Required roles determine
whether the rule can run. Optional roles refine proof or context. The input contract fixes each role's numeric scale
and database type. Use °C for temperature, Pa for pressure, L/s for flow, kW for power, kWh for energy, %RH on a
0–100 scale, fractions on 0–1, and status values on 0–1. SI conversion occurs at ingest. Rules contain SI thresholds
and never convert values.

## Tuning today

Use `python sql/fdd/render_rule.py SV-RANGE --params '{"confirm_min":10}'` to render SQL with a validated
override. The Full NF app uses the defaults baked into the generated packs. Its rule view shows bindings and
opens plots. Editing a shipped default requires rebuilding the packs and deploying the resulting revision.
The sweep catalog records the role limits in SI. The current render controls cover timing and scale factors,
while the range and spike templates still carry their base limits.

## Verification

```bash
node --test nf-app/tests/engines.test.mjs nf-app/tests/sv-sweeps.test.mjs
python -m pytest tests/parity -q
python scripts/nf/build_rule_catalog.py --check
python scripts/nf/build_sql_pack.py --check
python scripts/nf/gen_rule_docs.py --check
python scripts/nf/gen_cookbook.py --check
```

The [rule catalog](rules/) is the compact index. The [SQL cookbook](rules/sql-cookbook.html) lists parameters, roles, units
and outputs and links each SQL file. See the [units convention](rules/sql-cookbook.html#units-convention) for the conversion boundary.
To run a rule on your own database see [Using SQL rules outside Open-FDD](rules/borrowing-sql.html).
