# PostgreSQL version

`rules/` holds 77 PostgreSQL templates. Use the shared parent `registry.yaml`, `tuning_catalog.json`, `render_rule.py` and `input_contract.sql`. `postgres/postgres_helpers.sql` (the only copy) defines the safe numeric conversion needed by occupancy rules. The parent `tuning_storage.sql` is a configuration/result schema starting point.

Render: `python sql/fdd/render_rule.py FC1`. The pack is executed in-process by PGlite and SQLite (`nf-app/tests/engines.test.mjs`) and compared with the pandas oracle in `tests/parity/`.

No PostgreSQL server was available on the preparation host. Execute all target tests before claiming PostgreSQL qualification.
