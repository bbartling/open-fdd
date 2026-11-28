---
name: add-or-tune-fdd-rule
description: Add or tune an FDD rule in sql/fdd and rebuild the catalog, SQL packs and rule docs.
---
# Add or tune an FDD rule

1. Edit the rule SQL in `sql/fdd/postgres/rules/` and its entry in `sql/fdd/registry.yaml` (roles, parameters with
   SI units and defaults, `confirm_seconds`). New legacy role keys: `sql/fdd/role_map.json`; NF-class overrides:
   `nf-app/rules/role_overrides.json`. Canonical names stay in `roles/openfdd-roles.json`. Thresholds are SI and the
   unit is shown; never convert in SQL. One user-facing timer: `confirm_min` or the single window length. Other delays
   are `internal_constants`. Shipped numbers are SI starters. Cite Guideline 36 from `docs/rules/defaults-g36.md`; do
   not copy a G36 table value in as the default unless the registry already says so.
2. Sensor sweeps (`SV-RANGE`, `SV-SPIKE`, `SV-FLATLINE`, `SV-STALE`, `SV-RATE`) return one row per sensor.
   `SV-STALE` is missing data only. A stuck but polled value is `SV-FLATLINE`.
3. Saved site and equipment tuning must keep applying. Renaming or retiring a rule id needs a tested migration of
   saved overrides (`nf-app/static/rule-tuning.js` migrates parameter keys, not rule ids).
4. Rebuild (generated files, never hand-edit):
   `python3 scripts/nf/build_rule_catalog.py` then `python3 scripts/nf/build_sql_pack.py` then
   `python3 scripts/nf/gen_rule_docs.py`. DuckDB helpers, when the SQL needs them, stay in
   `sql/fdd/duckdb/duckdb_helpers.sql` (`duckdb>=2.0.1`).
5. Engine parity: `node --test nf-app/tests/engines.test.mjs` (DuckDB runs the Postgres pack) and
   `python -m pytest tests/parity -q` (pandas against Node DuckDB).
6. pandas parity: if the rule has a pandas twin in `open_fdd/rules`, keep it equal except a row in
   `open_fdd/data/parity_known_differences.json`. Harness: `tests/parity/`, workflow `.github/workflows/parity.yml`.
7. Full check: `node --test nf-app/tests/*.test.mjs`, then `python3 scripts/nf/build_rule_catalog.py --check`,
   `python3 scripts/nf/build_sql_pack.py --check` and `python3 scripts/nf/gen_rule_docs.py --check`.

Do not add name, suffix or key-syntax matching to find points. Binding is NF class, else Haystack markers, onto a
223P role (`DATA_CONTRACT.md`). Do not edit `sql/fdd` while another change to it is in flight.
