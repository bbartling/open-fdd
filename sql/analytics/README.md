# Analytics SQL pack (Soft-OPEN)

Scientific analytics bodies live here (versioned + hash-pinned with `sql/contract`).
Rust `timescale_analytics.rs` binds `$1` site/building parameters only — it must not
fork equations. BPS and OSS pin the same pack hash.

| Path | Role |
| --- | --- |
| `registry.json` | Query id → SQL path inventory |
| `postgres/queries/*.sql` | Parameterized scientific bodies |

Inventory target: 32 POST routes + catalog + 29 RCx presets
(`.cursor/agents/sql_analytics_inventory_20261014.md`). Soft-OPEN ≠ FQ until every
route has equation SQL + known-answer fixtures.

**Forbidden:** dual-write, Parquet co-canonical, DataFusion product path, equation forks.
