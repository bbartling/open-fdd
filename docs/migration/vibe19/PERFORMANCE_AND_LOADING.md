# Performance, loading paths, and pitfalls (App 19)

Guide for AI agents and vibe-coders building on this stack. **Read before adding data loaders, new pages, or alternate front ends.**

**Related:** [`DATA_CONTRACT.md`](../DATA_CONTRACT.md) · [`../AGENTS.md`](../AGENTS.md) (AI quick rules)

---

## Where data enters pandas

| Path | Module | When to use |
| --- | --- | --- |
| **CSV → Feather (recommended)** | `haystack_rdf/feather_cache.read_history_csv` | Default dashboard load; auto-resample + disk cache |
| **CSV → Parquet (Rust, stage 1)** | `rust_fdd_core` → `fdd_cli ingest` → `.cache/parquet/` | DataFusion SQL rules, benchmarks, future prod path |
| **CSV direct** | `pd.read_csv` + contract in `DATA_CONTRACT.md` | Custom scripts; call `maybe_downsample_to_5min` yourself |
| **Feather direct** | `pd.read_feather` from `.cache/feather/` | Only if you understand cache invalidation (mtime in `.meta.json`) |
| **SQL / other** | DataFusion (`sql_rules/`) or DuckDB analyst path | Deterministic rules → SQL; debug rollups → DuckDB |

**Do not** call Haystack SPARQL on every HTTP request for path discovery — use filesystem discovery (`raw_data_source_paths()` in `generate_dashboard.py`).

**Migration:** Python pandas remains **oracle** until `fdd_cli compare` documents parity. See [`RUST_CORE_STAGE1.md`](RUST_CORE_STAGE1.md).

---

## Timestamp grid / resampling (required)

Historian rows may be 1-min, 5-min, 15-min, etc. **Before FDD rules**, normalize grid:

```python
from haystack_rdf.timeseries_grid import maybe_downsample_to_5min, effective_poll_seconds

df = maybe_downsample_to_5min(df, ts_col="timestamp")
poll = df.attrs.get("effective_poll_seconds")  # 300 if sub-5-min was downsampled
```

| Median Δt | Action |
| --- | --- |
| **< 5 minutes** | Resample to **5-minute means** (`resample("300s").mean()`) |
| **≥ 5 minutes** | **No resampling** — keep native cadence (e.g. 15-min stays 15-min) |

Use `effective_poll_seconds` (or `manifest grid_minutes`) for `confirm_fault` rollups — **never hardcode 900** unless data is actually 15-min.

---

## Feather sidecar cache

- **Location:** `fdd_app/backend/.cache/feather/` (gitignored)
- **Key:** SHA256 of source CSV path
- **Invalidation:** Source CSV `mtime_ns` in `.meta.json`
- **Contents:** Post-normalized DataFrame (UTC `timestamp`, `timestamp_local`, downsampled if needed)
- **Dependency:** `pyarrow` (in `requirements-dev.txt`)

```python
from pathlib import Path
from haystack_rdf.feather_cache import read_history_csv
from shared.data_config import get_config

cfg = get_config()
df = read_history_csv(Path(".../history_wide.csv"), tz=cfg.site_timezone())
```

After load, check `df.attrs.get("effective_poll_seconds", cfg.poll_seconds())`.

---

## In-memory dashboard cache

| Layer | Module | Key |
| --- | --- | --- |
| Raw CSV bundle | `dashboard_cache.get_raw_data` | All historian CSV mtimes |
| Computed metrics | `dashboard_cache.get_context` | `(params_hash, page_id)` |
| Plotly HTML body | `dashboard_cache.get_body` | `(params_hash, page_id)` |

**Shell-first UX:** HTML pages return instantly; `dashboard_tune.js` POSTs `/api/refresh/<page>` for chart bodies.

**Stampede protection:** Concurrent requests wait on in-flight compute instead of duplicating work.

---

## Known bottlenecks (fixed — do not reintroduce)

| Problem | Symptom | Fix |
| --- | --- | --- |
| SPARQL path discovery per request | 25s+ every refresh | Filesystem `discover_historian_bundles` + mtime cache |
| Repeated `read_csv` | 8–10s cold start | Feather sidecars (~2s cold, ~0s warm) |
| Zone stats tz_convert in inner loop | 15–20s index compute | Precompute occupancy/season masks per AHU |
| SPARQL before JSON model | Slow equipment lists | `list_equipment` tries `model.json` first |
| “Framework slowness” (Flask/FastAPI) | Misdiagnosed as web-layer issue | CPU-bound pandas; async won't help — cache + downsample; keep heavy endpoints sync so they run in the threadpool |

---

## Custom vibe apps — checklist

1. Load via `read_history_csv` or replicate its steps (parse UTC → local → maybe_downsample).
2. Set `poll_seconds` from `effective_poll_seconds` or manifest.
3. Use `confirm_fault(raw, poll_seconds=...)` from Open-FDD cookbook pattern.
4. Map columns via `columns.csv` / Haystack roles — not raw vendor names alone.
5. Cache expensive compute; never block HTTP on full recompute when params unchanged.
6. For deploy, bake static `site/` or run Docker `deploy` mode — see `DEPLOY.md`.

---

## Flask vs FastAPI

The app now runs on **FastAPI** (migrated from Flask). The move was **not** for raw request speed — bottlenecks are data loading + pandas compute, not the web framework, and CPU-bound work still runs in Starlette's threadpool. It was for the **API-first / forkable** direction: typed Pydantic request bodies, automatic `/openapi.json` + `/docs`, and a stable contract for the custom-rule / ML lab (`/api/rules`, `/api/rules/run`). This also aligns with the open-fdd bridge, which is FastAPI + routers.

Performance rule still holds: **never block HTTP on full recompute** — keep `dashboard_cache` warm and downsample. Heavy pandas endpoints stay `def` (sync) so Starlette runs them in a worker thread rather than the event loop.

---

## Apache Arrow — what’s next

We use Arrow via **Feather** (Python) and **Parquet** (Rust `fdd_store`, stage 1). See [`RUST_CORE_STAGE1.md`](RUST_CORE_STAGE1.md) and [`ROADMAP_ARROW_PLUGINS_ML.md`](ROADMAP_ARROW_PLUGINS_ML.md).

| Layer | Today | Production direction |
| --- | --- | --- |
| Disk cache | Feather (`pyarrow`) + Rust Parquet sidecars | Parquet primary for rules |
| Rule engine | pandas cookbook (oracle) | **DataFusion SQL** (`sql_rules/`) |
| Analyst/debug | DuckDB on Feather/Parquet | Stays optional — not prod rule engine |

| Next step | Expected win |
| --- | --- |
| **Rust ingest** on BUILDING_100 | Measured cold CSV → Parquet timing |
| **DataFusion SQL** rule batch | Replace pandas for threshold/rollup rules |
| **DuckDB** on Feather/Parquet | Zone/plant rollups (analyst path) |
| **fdd_cli compare** | Documented pandas↔SQL parity |

Keep **new standard FDD rules out of pandas** unless documented in [`PANDAS_TO_SQL_RULE_MIGRATION.md`](PANDAS_TO_SQL_RULE_MIGRATION.md).

---

## Tests

```bash
cd fdd_app
pytest test_timeseries_grid.py test_economizer_diagnostics.py test_haystack_rdf.py -q
```
