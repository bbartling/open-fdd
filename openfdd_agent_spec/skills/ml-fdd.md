---
name: ml-fdd
description: Run or extend the ML FDD tools of the PyPI package (open-fdd-ml, open_fdd.ml) and the SQL z-score; score any detector on the public LBNL AHU data against the rule pack.
---
# ML FDD and SQL anomaly tools (`pip install "open-fdd[ml]"`)

Guide and results: `docs/ml/lbnl-ahu-benchmark.md`. Tool list: `docs/pypi-agent-tools.md`.

1. **Benchmark first.** `open-fdd-ml download` (LBNL single-duct AHU subset, CC BY 4.0, into
   `$OPENFDD_ML_CACHE` or `~/.cache/open-fdd/lbnl`; never commit it), then `open-fdd-ml benchmark --out b.md --json b.json`.
   A new detector merges only with a benchmark row and its fault-free FPR. If it loses to `rules (tuned)`, say so.
2. **Detect on a device folder** (`history_wide.csv` in SI + `column_map.json`, same as `open-fdd-anomaly`; build one
   with `open-fdd-ml make-folder CSV --map ROLE=COLUMN ... --out DIR`, `--from-lbnl FILE` or `--example`):
   `open-fdd-ml detect FOLDER --method pca|grey_box|ocsvm|copod|zscore|mad --train-until YYYY-MM-DD --out DIR`.
   Learning methods need exactly one training source: `--train KNOWN_GOOD_FOLDER`, `--train-until` (fit before,
   score after) or `--exploratory-self-fit` (never call its flags faults against a healthy baseline). Without one
   the command exits 2. `flags.csv` has a `phase` column; `summary.json` counts evaluation rows only and records
   the training source, span, active rows, overlap with the target and seed. A supplied training folder is the
   operator's assertion of healthy data, not a verified maintenance label. PCA writes `contributions.csv/png`.
   `summary.json` `roles` / `roles_used` are the roles actually scored; `roles_missing` the configured ones the folder lacks.
   `flags.csv` explains each flag: `flagged_roles` (zscore/mad), `top_role` + `top_share` (pca), `top_residual` +
   `ratio_<residual>` (grey_box). With zero flags the contribution plot says so instead of showing bars.
3. **SQL z-score**: `open-fdd-anomaly screen FOLDER --out DIR --methods zscore --engine sql` runs
   `sql/analytics/anomaly_zscore.sql` (portable: PostgreSQL/Timescale, DuckDB, SQLite) over `fdd.point` +
   `fdd.input_sample`. Python: `open_fdd.analytics.sql_anomaly.run_zscore_sql(conn, engine, window=..., ...)`.
   Edit the repo SQL and copy it byte for byte to `open_fdd/data/anomaly_zscore.sql`; `tests/test_sql_anomaly_zscore.py`
   proves SQL == `rolling_zscore_flags` on the seeded parity dataset (Postgres in the parity workflow's postgres job).
4. Keep `open_fdd.ml` out of the core import path (a test checks `import open_fdd` loads no sklearn). COPOD needs `pyod`
   (`open-fdd[ml-copod]`, pulls numba); its tests skip without it.
5. **Anomaly CLI** (`open-fdd[anomaly]`): `open-fdd-anomaly screen FOLDER --out DIR` (z-score, MAD, STL, Isolation
   Forest; `--engine pandas|sql`), `open-fdd-anomaly report FOLDER --out DIR --month YYYY-MM [--compile]` (Typst / PDF).
   Anomalies are single-signal outliers, not faults: the benchmark shows z-score / MAD flag healthy hours as often.
   For agents and scheduled runs use `--no-plots --json --tz <IANA zone>`, and read `summary.json` rather than the PNGs.
   `screen` and `detect` share one activity policy (default `--activity proof`): equipment points are assessed only
   while operating proof is on. Read `activity.json` / `summary.json` `activity` before calling a zero-flag result
   clean: `no_run_proof`, `no_active_rows` or a small `assessed_rows` means unassessed, not healthy.
6. **Dependencies**: floors only, at the latest stable releases (pandas 3.1.1, numpy 2.5.5, scikit-learn 1.9.1,
   SciPy 1.18.1, statsmodels 0.15.0, DuckDB 2.0.0, pyod 3.6.8, ...; see `CHANGELOG.md`), with `python_version` markers
   where a release dropped 3.10 / 3.11. Keep the 3.10-3.15 matrix green; add a marker, never an `==` pin.
7. Tests: `pytest tests/test_ml_fdd.py tests/test_sql_anomaly_zscore.py`. Results tables hold measured numbers only.
8. **Which methods apply**: run `open-fdd-ml methods FOLDER [--json]` before `detect`. It names the roles each
   method needs and why a method cannot run on that folder. On a furnace, RTU or heat pump (no MAT), gray-box uses
   the single-zone `heat_rise` / `cool_drop` residuals; their thresholds come from that unit's own training rows.
