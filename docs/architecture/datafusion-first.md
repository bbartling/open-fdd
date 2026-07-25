---
title: DataFusion-first policy
parent: Architecture
nav_order: 10
---

# DataFusion-first policy

**Status:** target contract (audit 2026-07-25). Implementation deepens in migration PR2+.

For tabular building telemetry computation:

> If the operation can reasonably be expressed as DataFusion SQL, it belongs in DataFusion SQL.

Pandas may remain as:

| Class | When |
|-------|------|
| UI boundary | Tiny final frame for Streamlit/Plotly **after** DF aggregation |
| Test oracle | Independent reference vs SQL (online Pandas cookbook + vibe19 playground) |
| Non-SQL | ZIP/IO, IDF, DOCX, config parse, Plotly figure build |
| In-tree catalog | `services/ui/app/rules/` — **do not delete**; emergency FDD only with `OPENFDD_ALLOW_PANDAS_FDD=1` |

## Forbidden

- Silent pandas FDD fallback when DataFusion fails
- Millions of raw rows into Streamlit for Python downsample
- Downsampling before fault math
- Vibe-coding away the pandas cookbook because SQL exists
- A second Streamlit app for WattLab/EnergyPlus (keep Export handoff in the united UI)

## Production FDD today

Canonical path: `sql_rules/` + `crates/fdd_rules` + `POST /api/fdd/run`.  
Pandas cookbook only with explicit `OPENFDD_ALLOW_PANDAS_FDD=1`.

UI: **one** Streamlit app (`services/ui`) for vibe19 + WattLab export.

See [VIBE19_VIBE20_OPENFDD_AUDIT.md](../migration/VIBE19_VIBE20_OPENFDD_AUDIT.md) · [Rule Cookbook](../rules/cookbook/).
