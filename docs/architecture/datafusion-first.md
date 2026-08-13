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
| UI boundary | Tiny final frame for React SPA/Plotly **after** DF aggregation |
| Test oracle | Independent reference vs SQL (online Pandas cookbook + vibe19 playground) |
| Non-SQL | ZIP/IO, IDF, DOCX, config parse, Plotly figure build |
| In-tree catalog | `frontend/web/app/rules/` — **do not delete**; emergency FDD only with `OPENFDD_ALLOW_PANDAS_FDD=1` |

## Forbidden

- Silent pandas FDD fallback when DataFusion fails
- Millions of raw rows into React for Python downsample
- Downsampling before fault math
- Vibe-coding away the pandas cookbook because SQL exists
- A second React app for WattLab/EnergyPlus (keep Export handoff in the united UI)

## Production FDD today

Canonical path: `sql_rules/` + `crates/fdd_rules` + `POST /api/fdd/run`.  
Pandas cookbook only with explicit `OPENFDD_ALLOW_PANDAS_FDD=1`.

UI: **one** React app (`frontend/web`) for vibe19 + WattLab export as the
**default** product surface. Phase 1 authorizes a React SPA behind a flag
([ADR-001](adr-001-react-rust-modernization.md)); React remains fallback
until Phase 2. Deterministic FDD stays DataFusion SQL either way.

See [VIBE19_VIBE20_OPENFDD_AUDIT.md](../migration/VIBE19_VIBE20_OPENFDD_AUDIT.md) · [Rule Cookbook](../rules/cookbook/) · [React/Rust modernization](../migration/react-rust/).
