# Open-FDD stress gate (SPARQL → Timescale → SQL FDD ≈ pandas)

Soft-OPEN Track C port of the BPS `scripts/stress/` agent harness. Same scientific
lesson (SPARQL → timeseries → pandas ↔ warehouse SQL); Open-FDD route names and
JWT auth. **Soft-OPEN ≠ FQ.** Synthetic sites only — no private consumer names.

Vocabulary is **Project Haystack RDF** / package `ofdd:` Turtle. Production FDD
is **Timescale SQL** on tip Soft-OPEN; pandas runs **only** in this gate (and
oracle CI) — never on the product request path.

### Gate 08 quality contract (#1253)

| Surface | Quality layer | Role in gate 08 |
| --- | --- | --- |
| `POST /api/fdd/run` (Timescale SQL) | N/A (SQL has no OUT_OF_RANGE filter) | Product FDD — **strict match target** |
| Pandas SQL-aligned oracle (`quality=False`) | OFF | **Contractual oracle** for SQL hours |
| Full `run_rule` (`quality=True`) | ON | DIAG / reconciliation only |

Fail-closed: SQL must match quality-OFF. Do not treat quality-ON hours as the SQL
pass criterion. `--allow-satdev-drift` logs a diagnostic warning for a mismatch but the strict gate remains BLOCKED. Unit CI:
`tests/rules/test_sql_quality_contract.py`. Cookbook DF columns are Haystack
roles (`discharge-air-temp`, …) — not warehouse short aliases (`sat` / `sat_sp`).
Full write-up: [`docs/operations/SQL_PANDAS_QUALITY_CONTRACT.md`](../../docs/operations/SQL_PANDAS_QUALITY_CONTRACT.md).

## What we prove (gate matrix)

| Gate | Script | Proof | Soft-OPEN status |
| --- | --- | --- | --- |
| A1 | `01_sparql_model.py` | SPARQL + package TTL + predefined catalog | Landed (T13) |
| A2 | `02_sparql_fc1_points.py` | FC1 roles via SPARQL / templates | Optional later |
| A3 | `03_sparql_zone_dataframe.py` | SPARQL → point-resolve/historian → pandas DF | Landed (T13) |
| B–E | `04`–`07` | Local Timescale / warehouse (may stay BPS-side) | Optional |
| F | `08_sql_vs_pandas_sparql.py` | Synthetic pack SQL FDD ↔ pandas via SPARQL DF; fail-closed (#1253) | Landed (T14) |
| G | `09_analytics_sql_vs_pandas.py` | Comfort history percentage/coverage and economizer returned-input arithmetic | Landed, bounded checks (T15) |
| H | `10_model_crud_helpers.py` | `PUT /api/model/semantic-meta` dry_run + CAS; overlay Turtle; `POST /api/model/equip` dry_run; agent-context; `/api/model/ttl`; SPARQL pack ∪ overlay | Soft-OPEN (≠ C2–C6 FQ) |
| Runner | `run_gate.py` + `helpers.py` | `--host` / `--base-url` JWT | **This PR (T12)** |

### Gate verdict (fail-closed, QA-01)

`run_gate.py` prints a per-step summary and one verdict. Required steps are 01,
03, 08, 09 and 10. 02, seed and 04–07 are optional: when absent they are
reported `NOT_LANDED`, and when present they run and must pass.

| Verdict | Exit | When |
| --- | --- | --- |
| `PASS` | 0 | Every required step exited 0 and wrote fresh v2 PASS evidence with matching run/scope/script identity, required assertions and nonzero declared comparisons |
| `FAIL` | 1 | Any step exited non-zero (other than 2), timed out (`--step-timeout`, default 1800 s), or exited 0 with a non-PASS result file |
| `BLOCKED` | 2 | A required step is missing or skipped (`--skip-b50-parity`, `--skip-analytics`), exited 2, or exited 0 without a result file |

Each child records checks through `helpers.record_check` and its verdict through
`helpers.run_child` to `OPENFDD_STRESS_RESULT_FILE`. Exit zero without assertions
is BLOCKED. The parent validates the per-run nonce, target, building, child script
hash and counts; retained summary JSON includes child evidence. If supplied,
`--expected-version` must match each child's real health response. These hashes
bind reported bytes; they are not a deployment authenticity attestation.

Gate01 parses the Haystack graph with RDFLib and no longer accepts a legacy
mapping graph or a prefix/name substring as semantic proof. Gate03 selects a
measured temperature point by semantic tags, uses its actual IRI and blocks on
missing history; it cannot hide a broken explicit binding behind another reader.
This single-point transport smoke does not approve an FDD input automatically.
Use [semantic known-answer qualification](../qualification/semantic/README.md)
for exact semantic expectations and negative controls.

Gate08 compares only the single successfully evaluated SQL row with exact
`(rule_id, equipment_id)` identity and needs `--min-rules` (default: all three)
comparisons. Gate 09 needs `--min-economizer-points` and
`--min-comfort-equipment` (default 1 each). Zero rows or missing fixtures exit
2 (BLOCKED), never 0. Ambiguous role candidates and unsupported irregular/COV
cadence block the current fixed300second oracle; they do not become equation
failures or silently pass. A waived SATDEV mismatch remains BLOCKED. Gate09 uses
the active RCx preset request/rows contract and checks the oracle sample count
as well as comfort percentage. Economizer checks are returned-input arithmetic,
not a complete independent raw-history oracle. Gate08/09 still need authoritative
opaque binding joins and explicit unit normalization for broader qualification. Gate10 cannot pass CRUD functionality with a
viewer denial, missing CAS revision or missing/unparsed TTL.

The stress HTTP client refuses cross-origin requests and redirects, enforces
500requests/32MiBresponse bounds per client, and avoids logging auth response
bodies. The runner forwards passwords through environment rather than child argv;
prefer supplying credentials via environment initially too. This is bounded
correctness tooling, not a throughput benchmark or a substitute for provider/job
crash, autoscaling and gap qualification.

`--summary-json PATH` writes the step table and child evidence. Offline
regressions: `tests/qualification/test_stress_gate_fail_closed.py`.

## Open-FDD API map (vs BPS)

| Need | Open-FDD | BPS twin |
| --- | --- | --- |
| Login | `POST /api/auth/login` → `token` / `access_token` | same path, `access_token` |
| Health | `GET /api/health` (`ok`) | same |
| SPARQL | `POST /api/model/sparql` + `building_id` | `POST /api/sparql` |
| Catalog | `GET /api/model/sparql/predefined` | examples catalog |
| TTL | `GET /api/csv/import/package/mapping/ttl?building_id=` | `GET /api/model/ttl` |
| Readings | `GET /api/timeseries/readings` | `GET /api/points/{id}/timeseries` |
| Historian | `GET\|POST /api/historian/query` | point timeseries |
| Default port | **8080** | often 8090 |

## Run — Linux on the lab box

```bash
./scripts/openfdd_stack_up.sh portal    # current NF/CSV + Timescale stack
export OPENFDD_AGENT_PASSWORD=…          # never commit
export OPENFDD_STRESS_BUILDING_ID=SYNTH_01   # synthetic id only
python scripts/stress/run_gate.py --building-id SYNTH_01 \
  --expected-version '<exact /api/health version+commit>' --summary-json /tmp/stress.json
```

## Run — Windows laptop → lab API

```bat
set OPENFDD_AGENT_PASSWORD=…
python scripts\stress\run_gate.py --host <lab-ip> --building-id SYNTH_01
```

Non-localhost `--host` (or `--remote-api`) skips local-DB-only steps. Full URL:

```bat
python scripts\stress\run_gate.py --base-url http://<lab-ip>:8080 --building-id SYNTH_01
```

Env: `OPENFDD_STRESS_BASE` / `OPENFDD_API_BASE`, `OPENFDD_STRESS_USER`,
`OPENFDD_STRESS_PASS` / `OPENFDD_AGENT_PASSWORD`, `OPENFDD_STRESS_BUILDING_ID`.

Deps: stdlib only for helpers/runner. Gate scripts that build DataFrames need
`pip install -r scripts/qualification/requirements.txt` (and `open-fdd[oracle]`
for pandas rule oracles). Python stays outside the product runtime.

## Beginner path

Prefer [`scripts/lessons/`](../lessons/) for a human/agent teach walkthrough, then
this gate for regression.

## Related

- Quality contract: [`docs/operations/SQL_PANDAS_QUALITY_CONTRACT.md`](../../docs/operations/SQL_PANDAS_QUALITY_CONTRACT.md) · [#1253](https://github.com/bbartling/open-fdd/issues/1253)
- Haystack RDF: [#997](https://github.com/bbartling/open-fdd/issues/997), [#1123](https://github.com/bbartling/open-fdd/issues/1123)
