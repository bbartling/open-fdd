---
title: DataFusion-first policy
parent: Architecture
nav_order: 10
---

# DataFusion-first policy

**Status:** target contract (audit 2026-07-25). Implementation deepens in migration PR2+.

For tabular building telemetry computation:

> If the operation can reasonably be expressed as DataFusion SQL, it belongs in DataFusion SQL.

## Allowed pandas

| Class | When |
|-------|------|
| UI boundary | Tiny final frame for Streamlit/Plotly **after** DF aggregation |
| Test oracle | Independent reference vs SQL |
| Non-SQL | ZIP/IO, IDF, DOCX, config parse, Plotly figure build |

## Forbidden

- Silent pandas FDD fallback when DataFusion fails
- Millions of raw rows into Streamlit for Python downsample
- Downsampling before fault math

## Production FDD today

Canonical path: `sql_rules/` + `crates/fdd_rules` + `POST /api/fdd/run`.  
Pandas cookbook only with explicit `OPENFDD_ALLOW_PANDAS_FDD=1`.

See [VIBE19_VIBE20_OPENFDD_AUDIT.md](../migration/VIBE19_VIBE20_OPENFDD_AUDIT.md).
