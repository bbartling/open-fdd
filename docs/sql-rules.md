---
title: Writing SQL rules
nav_order: 5
---

# Write a SQL rule

PostgreSQL is the production FDD source. The SQLite pack is generated from it for smaller NF hosts. Keep every rule
site-neutral and use SI values at the rule boundary.

## Rule contract

The FDD engine loads a scoped, typed `history` table: one equipment and timestamp per row, with one SI column per
role. `weather` contains as-of weather data; `equipment` contains model and operational context. A rule query receives
those tables and its tuned parameters, then returns one row per equipment with its `equipment_id` and declared output
columns. Sensor sweeps use the long-form sensor relation and return one row per assessed sensor series.

Rules must not read NF tables directly, perform unit conversion, or infer scales from values. Missing, unknown, or
unusable input remains unknown; it must not be converted to a healthy zero. Keep operational gates and coverage
requirements explicit in the SQL.

## Add or change a rule

1. Edit or add `sql/fdd/postgres/rules/<rule>.sql`.
2. Declare the rule, equipment kinds, required and optional roles, parameters, units, confirmation time, and output
   columns in `sql/fdd/registry.yaml` and `sql/fdd/tuning_catalog.json`.
3. Add any new canonical role in `sql/fdd/role_map.json` and its scale/type in `sql/fdd/input_contract.json`.
4. Render the rule and build the catalog and both packs:

   ```bash
   python3 scripts/nf/build_rule_catalog.py
   python3 scripts/nf/build_sql_pack.py
   python3 scripts/nf/gen_rule_docs.py
   python3 scripts/nf/gen_cookbook.py
   ```

5. Add a deterministic fixture that exercises the fault and healthy path. Check output columns, missing-data behavior,
   confirmation edges, operational gating, and relevant timeline rows.
6. Run the focused engine and parity tests below. Document a deliberate difference in
   `sql/fdd/KNOWN_DIFFERENCES.md` and the parity registry.

## Roles and units

Use the canonical role names in `role_map.json`. Equipment kinds restrict where a rule runs; required roles determine
whether the rule can run; optional roles refine proof or context. The input contract fixes each role's numeric scale
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

The generated [rule catalog](fdd-rules.html) is the compact index; the [SQL cookbook](rules/sql-cookbook.html)
contains the rendered rule SQL, parameters, roles, and outputs. See [Units](units.html) for the conversion boundary.
