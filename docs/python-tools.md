---
title: Python tools
nav_order: 16
---

# Python tools

Install the PyPI package with the extras needed for your task:

```bash
pip install "open-fdd[nf]"        # NF client, pandas frames, reference rules
pip install "open-fdd[reporting]" # reports
pip install "open-fdd[rdf]"       # Turtle reader
pip install "open-fdd[anomaly]"   # open-fdd-anomaly screening and reports
pip install "open-fdd[ml]"        # open-fdd-ml: ML detectors and the LBNL benchmark
pip install "open-fdd[ontology]"  # open-fdd-ontology-audit (add ontology-shacl for SHACL)
```

The full list of commands and modules is on the [PyPI agent tools](https://bbartling.github.io/open-fdd/pypi-agent-tools.html) page.

The Python package version is separate from the NF app version. Use `open-fdd-version --pretty` to inspect the
available version information.

## Read NF data

The NF client supports LAN console/API access and the Normal Online portal. Set the required URL and API credentials
in environment variables or a protected env file, then use read commands:

```bash
open-fdd-nf info
open-fdd-nf model
open-fdd-nf rules --days 7
open-fdd-nf sparql examples/sparql_data/ahu_points.rq --days 7   # SPARQL -> trend data -> pandas rules
```

The tools read NF and do not write to it. The portal key is read-only. See the
[API reference](fdd-data-access.html) for the underlying routes.

## Python API

```python
from datetime import datetime, timedelta, timezone
from open_fdd.nf import NFClient, load_model, equipment_frames
from open_fdd.rules import run_all

client = NFClient.from_env(via="lan")
model = load_model(client)
end = datetime.now(timezone.utc)
frames = equipment_frames(client, model, end - timedelta(days=7), end)
results = run_all(next(iter(frames.values())))
```

Frames contain SI values mapped to Haystack roles. The pandas rules are reference implementations. The production
engine is SQL. See [parity](rules/parity.html).

The package also provides ECM workbooks, reports, anomaly screening, and RDF readers. Use the CLI help for command
options. Source and installation extras are in the repository's pyproject.toml.

## Anomaly screening and SQL z-score

```bash
open-fdd-anomaly screen ./AHU_1 --out ./anomaly_out                          # z-score, MAD, STL, Isolation Forest
open-fdd-anomaly screen ./AHU_1 --out ./anomaly_sql --methods zscore --engine sql
```

`--engine sql` runs `sql/analytics/anomaly_zscore.sql`, a portable query over `fdd.point` and `fdd.input_sample`
(PostgreSQL / Timescale, DuckDB, SQLite), on an in-process SQLite copy. Its flags equal
`open_fdd.analytics.anomaly.detectors.rolling_zscore_flags` on each point's non-missing samples
(`tests/test_sql_anomaly_zscore.py`, including PostgreSQL in CI). On a database that already has the core tables use
`open_fdd.analytics.sql_anomaly.run_zscore_sql(conn, engine, window=..., threshold=...)`.

**Activity.** `screen` and `open-fdd-ml detect` share one policy (`open_fdd.analytics.anomaly.activity`). Each row
is `on`, `off`, `unoccupied` or `unknown`. The proof source is chosen per folder: an own status role first
(`fan-status` for AHUs, `> 0.5`), then a resolved `run-proof` column, then an own command (`fan-cmd`, `> 0.05`). A
missing value on the chosen source makes that row `unknown`; it does not fall back to the command. With the default
`--activity proof`, equipment points are screened only on `on` rows, and site/weather points (outdoor air
temperature and humidity) on every row. A point with nothing to assess is listed as `no_run_proof` (no proof role) or
`no_active_rows` (proof never on) rather than as a clean result. `--activity ungated` screens every row on purpose.
`activity.json`, the README and the scoreboard's `gate` / `assessed_rows` columns record the choice and the counts;
`open-fdd-ml detect` writes the same receipt under `activity` in `summary.json`.

## ML FDD (`open-fdd-ml`)

```bash
open-fdd-ml download                     # LBNL single-duct AHU subset (CC BY 4.0) -> ~/.cache/open-fdd/lbnl
open-fdd-ml benchmark --out bench.md     # rule pack vs PCA/SPE, gray-box, one-class SVM, z-score, MAD
# COPOD needs pip install "open-fdd[ml-copod]" (pyod); with open-fdd[ml] alone that row is skipped
open-fdd-ml detect ./AHU_1 --method grey_box --train-until 2026-06-01 --out ./ahu1_ml   # fit before, score after
# learning methods need --train, --train-until or --exploratory-self-fit; zscore/mad need no training
```

Method, data, mapping and results: [docs/ml/lbnl-ahu-benchmark.md](ml/lbnl-ahu-benchmark.md).

## Ontology audit and model doctor (`open-fdd-ontology-audit`)

Offline and read-only; NF is optional (#1569).

```bash
open-fdd-ontology-audit --example --out ./r                         # synthetic sheet + two-sensor AHU graph
open-fdd-ontology-audit req.xlsx --refresh --out ./r                # pinned Brick / 223P / Haystack, sha256-checked
open-fdd-ontology-audit req.xlsx --graph building.ttl --shacl --out ./r
open-fdd-ontology-audit --from-nf --out ./r                          # optional: the app's RDF export (open-fdd[nf])
```

Requirement statuses: `VERIFIED_TERM` (URI declared in the snapshot, not a semantic endorsement), `CANDIDATE_REVIEW`
(label match only), `MAPPING_REVIEW` (namespace known, term absent), `EXTENSION_REVIEW`, `SOURCE_UNAVAILABLE`.
Reports: `audit.xlsx/csv/json`, `doctor.md/json`, `terms.csv`. It never assigns rules or writes tags.

