# PostgreSQL version

`rules/` holds 77 PostgreSQL templates. Use the shared parent `registry.yaml`, `tuning_catalog.json`, `render_rule.py` and `input_contract.sql`. `postgres_helpers.sql` defines the safe numeric conversion needed by occupancy rules. The parent `tuning_storage.sql` is a configuration/result schema starting point.

Render: `python sql/render_rule.py FC1 --dialect postgres`. Execute/compare on a disposable PostgreSQL test database: set `FDD_TEST_DSN`, then `python parity.py --engine postgres --dialect postgres`. Source templates remain in `../original_datafusion/`; `../rules/` is the baseline PostgreSQL adaptation kept for reproducible rebuilds.

No PostgreSQL server was available on the preparation host. Execute all target tests before claiming PostgreSQL qualification. Exact CSV labels and oracle comparisons are shared with the generic warehouse version.
