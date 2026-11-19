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

A frame built outside the package, or one without `df.attrs`, needs its equipment context. Pass it explicitly, as
in `run_all(df, equipment_type="AHU", equipment_id="AHU-1")`; `run_rule` takes the same keywords. Explicit keywords
win over `df.attrs['equipment_type' | 'equipment_id' | 'site_id' | 'building_id']`, and `df` is not modified.
Columns must use the Haystack role names (`discharge-air-temp`, not `sat`). An unstamped frame has type `UNKNOWN`,
so every rule is `NOT_APPLICABLE_EQUIPMENT_TYPE`. `summarize(results)` (also from `open_fdd.rules`) groups the
statuses and lists the most-needed missing roles. When nothing was assessed it adds one `explanation` line, for
example `no rule was assessed: no equipment type: pass equipment_type= ...`.

The package also provides ECM workbooks, reports, anomaly screening, and RDF readers. Use the CLI help for command
options. Source and installation extras are in the repository's pyproject.toml.

## Device folder

`open-fdd-anomaly screen|report` and `open-fdd-ml detect` read a device folder. It needs no NF and no database.

- `history_wide.csv`: a `timestamp_utc` column (ISO 8601, UTC) and one column per point, in SI. That means degC,
  Pa, fractions 0-1 for commands and positions (0-100 % also works for commands), and 0/1 for status.
- `column_map.json`: `{"equipType": "AHU", "points": {"discharge-air-temp": "SAT", "fan-status": "SF_S"}}`. A role
  is a Haystack-style name or its short alias; `open-fdd-ml make-folder --list-roles` prints them.

```bash
open-fdd-ml make-folder trend.csv --out AHU_1 --time-col Time --tz America/Chicago \
    --map discharge-air-temp=SAT --map outside-air-temp=OAT --map fan-status=SF_S   # naive stamps read in --tz
open-fdd-ml make-folder --from-lbnl ~/.cache/open-fdd/lbnl/AHU_annual.csv --from 2018-06-01 --to 2018-06-30 --out AHU_1
open-fdd-ml make-folder --example --out demo_AHU                                     # two synthetic days
```

`make-folder` does not convert units. An unknown role is a warning, not an error. `open-fdd-ml make-folder --help`
repeats the format.

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
is `on`, `off`, `unoccupied` or `unknown`. The proof source is the run-proof contract (`sql/fdd/run_proof.json`,
`open_fdd.run_proof.derive_run_proof`), chosen per folder: a resolved `run-proof` column first, then an own status
role (`fan-status` first), then an own command (`fan-cmd` first), all running when `> 0.05`. A frame marked
`run_proof_resolved` counts only its `run-proof` column. A missing value on the chosen source makes that row
`unknown`; it does not fall back to another source. With the default
`--activity proof`, equipment points are screened only on `on` rows, and site/weather points (outdoor air
temperature and humidity) on every row. A point with nothing to assess is listed as `no_run_proof` (no proof role),
`no_known_proof` (a proof role with no known value on any row) or `no_active_rows` (proof never on) rather than as a
clean result. STL and Isolation Forest run on the `on` rows joined end to end, so STL's seasonal phase is not aligned
across off periods; read STL results on intermittently running equipment with that in mind. `--activity ungated` screens every row on purpose.
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

`summary.json` lists `roles_used`, `roles_missing` and `roles_configured`, where `roles` is the scored set. `flags.csv` names
what drove each flagged row: `flagged_roles` for zscore and mad, `top_role` / `top_share` for PCA, and `top_residual` and
`ratio_<residual>` for the gray-box method.

For PCA and the gray-box method, `flags.csv` also has an `assessment` column for each row: `assessed`, `inactive`,
`missing_inputs` or `no_residual`. `summary.json` reports `assessed_rows`, `unassessed_rows`, `unassessed_reasons` and
`assessed_coverage` (assessed / active scored rows; `null` with a reason when nothing was active). A quiet run with
low coverage means the model could not judge those rows, not that they were healthy. Methods that don't report
per-row assessment (zscore, mad) give `assessed_rows: null` and an `assessment_note`.

Method, data, mapping and results: [docs/ml/lbnl-ahu-benchmark.md](ml/lbnl-ahu-benchmark.md).

`open-fdd-ml methods` lists the roles each method needs, and `open-fdd-ml methods ./AHU_1 [--json]` says which
methods can run on that folder and why the others cannot. PCA, one-class SVM and COPOD need two non-constant
feature roles (`discharge-air-temp`, `mixed-air-temp`, `return-air-temp`, `outside-air-temp`,
`outside-air-damper`, `cooling-valve`, `fan-cmd`, `duct-static-pressure`, `zone-air-temp`, `heating-valve`).
The gray-box method needs one residual family. The AHU families are the mixed-air balance, the cooling-coil
delta-T, and SAT error while the valve modulates. With no mixed-air temperature it uses the single-zone family
instead (furnace, RTU, heat pump): supply minus zone (or return) temperature against the heating valve
(`heat_rise`), or against the cooling valve or compressor status (`cool_drop`). A 0-100 % command is read as a
fraction. A role that is mapped but has no data on active rows does not count, so an empty `zone-air-temp` falls back
to `return-air-temp`. For the trained methods `methods FOLDER` runs a dry `fit` on the folder, so `can_run` means
`fit` succeeds on it (one-class SVM and COPOD need 50 active rows in one operating mode), and the reason is the
detector's own error.

## Ontology audit and model doctor (`open-fdd-ontology-audit`)

Offline and read-only; NF is optional (#1569).

```bash
open-fdd-ontology-audit --example --out ./r                         # synthetic sheet + two-sensor AHU graph
open-fdd-ontology-audit req.xlsx --refresh --out ./r                # pinned Brick / 223P / Haystack, sha256-checked
open-fdd-ontology-audit req.xlsx --graph building.ttl --shacl --out ./r
open-fdd-ontology-audit --from-nf --out ./r                          # optional: the app's RDF export (open-fdd[nf])
open-fdd-ontology-audit --extensions --out ./r                       # Open-FDD extension terms: parent, label, definition
```

Requirement statuses: `VERIFIED_TERM` (URI declared in the snapshot, not a semantic endorsement), `CANDIDATE_REVIEW`
(label match only), `MAPPING_REVIEW` (namespace known, term absent), `EXTENSION_REVIEW`, `SOURCE_UNAVAILABLE`.
Reports: `audit.xlsx/csv/json`, `doctor.md/json`, `terms.csv`. It never assigns rules or writes tags.

`--extensions [ext.ttl]` checks the Open-FDD extension terms in a Turtle file (default: the shipped
`ofdd_engineering_quantities_v1.ttl`) against the #1569 policy and writes `extensions.json`. It flags a class or
property declared in a standard namespace, one whose `rdfs:subClassOf` / `rdfs:subPropertyOf` chain never reaches a
standard concept, a missing `rdfs:label` or `skos:definition` (or `rdfs:comment`), and an enum member with an
undeclared type. It only reports and never edits the vocabulary.

