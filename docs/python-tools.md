---
title: Python tools
nav_order: 16
---

# Python tools

Install the PyPI package with the extras needed for your task:

```bash
pip install open-fdd[nf]          # NF client, pandas frames, reference rules
pip install open-fdd[reporting]   # reports
pip install open-fdd[rdf]         # Turtle reader
pip install open-fdd[anomaly]     # open-fdd-anomaly screening and reports
pip install open-fdd[ml]          # open-fdd-ml: ML detectors and the LBNL benchmark
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

## ML FDD (`open-fdd-ml`)

```bash
open-fdd-ml download                     # LBNL single-duct AHU subset (CC BY 4.0) -> ~/.cache/open-fdd/lbnl
open-fdd-ml benchmark --out bench.md     # rule pack vs PCA/SPE, gray-box, one-class SVM, COPOD, z-score, MAD
open-fdd-ml detect ./AHU_1 --method grey_box --train-until 2026-06-01 --out ./ahu1_ml
```

Method, data, mapping and results: [docs/ml/lbnl-ahu-benchmark.md](ml/lbnl-ahu-benchmark.md).
