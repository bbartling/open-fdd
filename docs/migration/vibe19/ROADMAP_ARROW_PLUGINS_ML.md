# Roadmap — Arrow performance, custom rules, ML, generic data sources

Planning doc for vibe-coders and AI agents. **Not implemented yet** — use this to pick the next vertical slice.

**Related:** [`PERFORMANCE_AND_LOADING.md`](PERFORMANCE_AND_LOADING.md) · [`DATA_CONTRACT.md`](../DATA_CONTRACT.md) · [`OPENFDD_PARITY.md`](OPENFDD_PARITY.md) · [Open-FDD pandas cookbook](https://bbartling.github.io/open-fdd/rules/cookbook/pandas-cookbook.html)

---

## Where we are today (Arrow)

We use **Apache Arrow** in two paths:

| Layer | Today |
| --- | --- |
| Python disk cache | `haystack_rdf/feather_cache.py` — CSV → normalized DataFrame → `.feather` |
| **Rust disk cache (stage 1)** | `rust_fdd_core/fdd_store` — CSV → Arrow RecordBatch → `.cache/parquet/` |
| Rule engine (oracle) | pandas `cookbook_engine.py` |
| Rule engine (target) | DataFusion SQL — `sql_rules/` + `fdd_cli run-rules` |
| Analyst SQL | DuckDB rollups (`duckdb_rollups.py`) — debug only |
| open-fdd sidecar | HTTP DataFusion over `telemetry_pivot` export |

See [`RUST_CORE_STAGE1.md`](RUST_CORE_STAGE1.md) · [`PANDAS_TO_SQL_RULE_MIGRATION.md`](PANDAS_TO_SQL_RULE_MIGRATION.md).

---

## Arrow / columnar — recommended next steps (priority order)

### 1. Profile before rewriting (always)

Use `cProfile` or `py-spy` on a cold + warm `POST /api/refresh/index` and `zones`. Only optimize paths that show up. After the 2026 performance stack, typical warm refresh is sub-second — biggest gains may be on **zone rollups** and **multi-VAV** work, not the web framework.

### 2. Parquet sidecars — ✅ started (Rust)

`fdd_cli ingest` writes partitioned Parquet under `.cache/parquet/`. Python `read_history_parquet()` also exists. Next: wire dashboard warmup to prefer Parquet for SQL rule batch.

### 3. DataFusion SQL rules — ✅ started (8 rules)

`sql_rules/` + `fdd_cli run-rules`. Production path for deterministic FDD. DuckDB remains analyst/debug.

### 4. DuckDB on cached Arrow files (analyst / debug)

Load Feather/Parquet once; run SQL aggregations for:

- Zone comfort % by floor/season (many columns → one GROUP BY)
- OAT bins, weekly rollups across equipment
- Future multi-building hub

```text
CSV → read_history_csv() → Feather/Parquet on disk
                         → DuckDB read_parquet/read_ipc
                         → small result → pandas/Plotly
```

**Keep cookbook fault masks in pandas** unless a rule is ported to SQL for export parity. DuckDB is for **rollups and joins**, not replacing every `confirm_fault()`.

### 4. Arrow Table as loader interchange (medium)

```python
table = pa.feather.read_table(path)   # zero-copy where possible
df = table.to_pandas(types_mapper=...)  # only when rule engine needs pandas
```

Use when the same historian is read by multiple engines (pandas FDD + DuckDB stats). Avoid duplicate CSV parses.

### 5. Polars (optional, after profiling)

Polars uses Arrow internally. Good for:

- Vectorized groupbys on wide zone frames
- Lazy scan of Parquet directories

**Not** a wholesale replacement for Open-FDD pandas cookbook rules until parity tests exist.

### 6. What is usually *not* worth it

- Rewriting all rules in `pyarrow.compute` kernels — high cost, breaks cookbook parity
- Switching web frameworks **for speed** — CPU-bound pandas; cache + columnar load first. (We *did* move Flask → FastAPI, but for the API-first/forkable contract + Pydantic + OpenAPI, not throughput.)
- Live Arrow Flight / streaming — out of scope for offline CSV analyst app

---

## Custom Python faults (like legacy Open-FDD) — **not nuts**

The old analyst workflow allowed **site-specific pandas rules** alongside the catalog. That fits the “vibe your own building” product goal.

### Design principles

1. **Rules live on disk** in the fork/repo — `rules/plugins/` or `{BUILDING_ID}/rules/`
2. **Discovery at startup** — import registered modules; build a `RuleRegistry`
3. **API never executes arbitrary code** — HTTP only sends **known `rule_id`s** and **numeric param overrides**
4. **Pydantic validates boundaries** — manifests, API bodies, param ranges — not every DataFrame row
5. **Same pipeline** — raw mask → smooth → `confirm_fault()` → hours rollup → Plotly section

### Suggested plugin contract

```python
# rules/plugins/my_site_fc99.py
RULE = RuleManifest(
    id="FC99",
    title="Custom SAT hunting",
    pages=["ahu_1"],
    params=[ParamSpec(key="threshold", min=0, max=100, default=10)],
    required_roles=["sat", "fan_cmd"],
)

def compute(ctx: RuleContext) -> RuleResult:
    # ctx.df wide history, ctx.mapping, ctx.poll_seconds, ctx.params
    raw = (ctx.df["sat"].diff().abs() > ctx.params["threshold"])
  confirmed = confirm_fault(raw, poll_seconds=ctx.poll_seconds)
    return RuleResult(fault_series=confirmed, summary_hours=hours_true(confirmed, ctx.poll_seconds))
```

### Registration

| Mechanism | Audience |
| --- | --- |
| Python module + `RULE` manifest | Engineers / vibe-coders (primary) |
| Declarative JSON/YAML subset | Analysts who don’t write Python (phase 2) |
| Open-FDD SQL export | Parity with edge/SQL engine (optional) |

### Security model

| Allowed | Forbidden |
| --- | --- |
| Import plugins from configured directories | `exec()` / `eval()` on request body |
| Engineer edits files + restarts the server | Upload `.py` via `/api` without review |
| Pin + lock on exported client packages | Remote code execution in deploy `site/` |

---

## Pydantic — where it helps

Use **Pydantic v2** at system boundaries only:

| Model | Purpose |
| --- | --- |
| `RefreshRequest` | `params`, `note`, optional `page_id` |
| `SiteSettings` | occupancy, comfort (extends `shared/occupancy.py`) |
| `RuleManifest` / `ParamSpec` | plugin registry |
| `HistoryManifest` | `manifest.json` validation |
| `PageSpec` | optional mirror of `page_registry` for OpenAPI |

**Do not** wrap every pandas operation. Hot path stays numpy/pandas.

**Done:** request bodies are now typed FastAPI/Pydantic models in `fdd_app/backend/api_models.py` (`LoginBody`, `ConfigBody`, `RefreshBody`, `RunRuleBody`), validated automatically before merge into session — no manual `request.get_json()` parsing.

---

## Machine learning — keep the door open

ML is a **special case of custom rules**, not a separate product.

```text
history_wide → feature builder (pandas) → model.predict → boolean fault mask
           → confirm_fault() → same analytics_rollups / ECM cards
```

| Concern | Approach |
| --- | --- |
| Training | Offline notebook or script; artifacts in `models/` (gitignored or LFS) |
| Inference | Load frozen model in plugin `compute()`; cache model in process memory |
| Features | Declare `required_roles` in manifest; fail gracefully if columns missing |
| UI | Same tune sliders for thresholds; optional “model version” in site settings |
| Deploy | Bake scores into static HTML or ship read-only model + manifest in client zip |

Start with **sklearn** (`.joblib`) on tabular features — not deep learning in the server request path.

---

## Generic data source → pandas (any backend)

The **contract** is a wide time-indexed DataFrame per equipment box — not “CSV only”.

### `HistorySource` protocol (proposed)

```python
class HistorySource(Protocol):
    def list_equipment(self, tag: str | None = None) -> list[str]: ...
    def load_wide(self, equipment_id: str, *, columns: list[str] | None = None) -> pd.DataFrame: ...
    def poll_seconds(self, equipment_id: str) -> int: ...
```

| Implementation | Status |
| --- | --- |
| `CsvHistorySource` | **Today** — `feather_cache` + `data_loader` |
| `SqlHistorySource` | Planned — DuckDB/pg/SQLite → wide DF; same grid rules |
| `ParquetHistorySource` | Planned — historian already exported to Parquet |
| `ApiHistorySource` | Out of scope for runtime — batch export to CSV/Parquet first |

**Rule engines and Plotly pages depend only on `HistorySource`**, not on how data arrived.

SQL example path:

```text
SQL DB → nightly export OR DuckDB ATTACH → wide DataFrame
       → maybe_downsample_to_5min → effective_poll_seconds
       → existing FDD engines unchanged
```

---

## Frontend morphability

The stack is now **FastAPI + server Plotly + vanilla JS**. The JSON API is the stable contract (typed + documented at `/openapi.json`); forks can swap the whole front end. Extension points:

| Stable contract | Fork can replace |
| --- | --- |
| `GET /<page>.html` shell | CSS theme, layout (`dashboard.css`) |
| `POST /api/refresh/<page_id>` → `{ content, analytics, params }` | Any JS that consumes JSON HTML |
| `GET /api/pages` nav tree | Custom nav component |
| `GET /api/rules` + `POST /api/rules/run` | Custom rule-lab UI (contract in `api_models.py`) |
| `page_registry.py` | Dynamic pages per site |
| `static/dashboard_tune.js` | React/Vue SPA **if** it calls the same APIs |
| `/openapi.json` | Auto-generate a typed client for any language |

**Headless mode (future):** `DASHBOARD_MODE=api` — JSON only, no Plotly HTML generation; front end 100% custom. FastAPI + `api_models.py` make this a small step.

---

## Suggested implementation order

1. **Pydantic API schemas** — small, immediate safety win (`shared/schemas.py`)
2. **`HistorySource` ABC + wrap current CSV loader** — no behavior change, enables SQL later
3. **DuckDB zone rollup experiment** — one page (`zones`), compare timing vs pandas
4. **Rule plugin registry** — one example custom rule + test fixture
5. **Parquet sidecar option** — behind flag in `feather_cache`
6. **ML plugin example** — sklearn anomaly on OAT residual; manifest + joblib

---

## Non-goals

- Executing user Python from HTTP
- Live BACnet / streaming historian in dashboard runtime
- Mandatory React rewrite
- Replacing Open-FDD edge — this repo stays the **offline analyst twin**
