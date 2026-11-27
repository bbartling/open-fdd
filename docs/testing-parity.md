---
title: Testing and parity
parent: Rules
nav_order: 6
---

# Testing and parity

## FDD rules

| What | Where |
|---|---|
| Runtime engines | Server-side Node DuckDB (`@duckdb/node-api` `2.0.1-r.1`) and Timescale. No other runtime engine and no fallback. |
| Three-way check | `pandas == SQL == SPARQL-client` in `parity.yml`. Known differences stay in `open_fdd/data/parity_known_differences.json`. |
| PR tier | `parity.yml`: 2 equipment × 3 days, `basic` and `edge`. Standalone PostgreSQL image `postgres:17.12`. |
| Nightly and pre-release | `parity-stress.yml`: cron `41 7 * * *`, and `workflow_dispatch` with input `ref`. 4×3 seeds 0–4 and 8×7 seed 0, `basic` and `edge`. |
| Timescale | `nf-app-ci.yml` job `TimescaleDB integration`: image `timescale/timescaledb:2.32.1-pg17`, 8 equipment × 7 days. |
| Tutorial only | `duckdb-tutorial.yml` runs when the tutorial, the parity package or `pack-postgres.json` changes. It is not the rule-pack stress run. |
| Who calls the PR tier | `security.yml` calls `parity.yml` on every pull request, on push to `master` and `release/**`, weekly, and on `workflow_dispatch`. |

| Library | Pin in the repo | Used for |
|---|---|---|
| `@duckdb/node-api` | `2.0.1-r.1` | Server-side Node DuckDB. Not a WASM build. |
| `pg` | `8.23.1` | Node client for the Timescale build |
| Timescale image | `timescale/timescaledb:2.32.1-pg17` | The Timescale CI job |
| `pandas` | `>=3.1.1` (`oracle` extra) | Reference rules |
| `duckdb` (Python) | `>=2.0.0` (`duckdb` extra) | Python test extra. The browser tutorial pins `duckdb==2.0.0`. |

## RDF

| What | Where |
|---|---|
| OntoEnv closure and Shifty | `ontology-223p.yml` on push to `master` and `release/**`, on every pull request, and on `workflow_dispatch`. The closure is vendored (`223p.ttl` sha256 `08f80bd6…`, the file at `https://open223.info/223p.ttl`, plus QUDT 3.4.0, SHACL, SKOS and VAEM). The job does not download it. OntoEnv 0.6.4 resolves `owl:imports` offline. Shifty 0.6.0 `minimum_severity` `Violation` is the verdict. |
| Query parity | `rdf-parity.yml` on pull requests into `master` or `release/**`, on `workflow_dispatch`, and as a job of `parity-stress.yml`. |
| Fixtures | `example_building.ttl`, the same graph plus a point with no `siteRef`, and `sql/fdd/roles-223p.ttl`. Queries are the panel set in `nf-app/static/sparql.js` plus role count, unit and `g36:ChilledWaterValve` binding queries. |
| Engines | rdflib evaluates those queries. Node uses `nf-app/static/sparql.js` through the vendored Oxigraph build, the same load and `store.query` path as `nf-app/hooks/sparql.js`. Sorted bindings, IRIs, and literal datatypes must match. A plain literal and `xsd:string` count as one term. |
| SHACL | Shifty's conforms flag and focus node on a small labeled/unlabeled fixture are the reference. The hook and the panel do not run SHACL. The test then checks that `nf-app` and `lite` `roles-223p.ttl` match `sql/fdd/roles-223p.ttl` byte for byte, and that the two `role-binding.json` copies match each other. |
| App answers | The Full hook and the local Python helper `open_fdd.sparql_eval` use Oxigraph 0.5.13. rdflib in this job is the parity engine for the fixture queries, not the answer the app returns. |

| Library | Pin |
|---|---|
| `rdflib` | `7.6.0` |
| `pyoxigraph` / vendored `oxigraph` | `0.5.13` |
| `ontoenv` | `0.6.4` |
| `pyshifty` | `0.6.0` (`minimum_severity` `Violation`; the library default is `info`) |
| `pyshacl` | `0.40.2` (opt-in cross-check, `advanced=True`, `inference` `none`; it does not set `conforms`) |
