---
name: open-fdd-clean-metrics
description: Preview and commit Grafana-style string metrics to Feather via POST /timeseries/clean-metrics — same path as Plots readiness — until plot-readiness is green.
---

# Open-FDD clean-metrics (Feather-safe, skill-driven)

## When to use

- **`GET /plots/frame?...&include_readiness=true`** or **`POST /timeseries/plot-readiness`** shows **`recommend_clean_metrics: true`** or per-column **`recommend_clean_metrics`** for messy metrics (e.g. `69.5 °F`, `17.8 psi`).
- Operator wants string/object columns **coerced to floats in Feather** so Plotly and **`POST /plots/fdd-frame`** see plain numbers.

## Preconditions

- Bridge up: `GET {bridge}/health`.
- Known **`site_id`** and driver **`source`** (usually `csv`; match the Plots / ingest source).
- Optional: MCP tool **`bridge_timeseries_clean_metrics`** (same JSON body as below).

## API (always use the bridge — no ad-hoc Python)

**`POST {bridge}/timeseries/clean-metrics`**

```json
{
  "site_id": "<uuid>",
  "source": "csv",
  "columns": null,
  "commit": false,
  "preview_limit": 12
}
```

- **`columns: null`** (omit in JSON) → auto-pick coercible columns via `suggest_coercible_columns`.
- **`columns: ["oat","sat"]`** → only those metrics (use when you must avoid touching other columns).
- **`columns: []`** → intentionally **no** columns coerced (empty list ≠ omit); use only when probing.

## Iterate until complete (agent loop)

1. **`POST .../timeseries/plot-readiness`** (or read embedded readiness from **`GET .../plots/frame?include_readiness=true`**) — if **`recommend_clean_metrics`** is false and **`ok`** is true for metrics, **stop**; Feather is already good enough for line plots.
2. **`POST .../timeseries/clean-metrics`** with **`commit: false`** — inspect **`suggested_columns`**, **`preview_before`**, **`preview_after`**, **`coercion_stats`**. If **`suggested_columns`** is empty, summarize for the human (may need ingest or different source).
3. **Human confirmation** (chat yes/no or explicit instruction) before any destructive step.
4. **`POST .../timeseries/clean-metrics`** with **`commit: true`** — rewrites Feather for that **`site_id` + `source`** (Feather path uses replace-on-success semantics). Response includes **`storage_path`** when committed.
5. **Re-check** plot-readiness (step 1). Repeat from step 2 **only** if a column still recommends clean (rare: mixed-type columns may need a second pass with explicit **`columns`**).

## MCP equivalent

`POST http://127.0.0.1:8090/tools/bridge_timeseries_clean_metrics` with the same JSON body (Bearer `OFDD_MCP_OFDD_API_KEY` if configured).

## Safety

- **`commit: true`** is **destructive** for that slice of Feather — never run without operator alignment.
- Do not invent **`site_id`**; use **`GET /sites`** or **`GET /assistant/readiness`**.

## References

- `open-fdd-bootstrap` skill — session health before this flow.
- `docs/howto/desktop_app.md`, `scripts/OPENCLAW_RUNBOOK.md` §1c (clean-metrics table).
- Bridge Swagger: **`POST /timeseries/clean-metrics`**, **`POST /timeseries/plot-readiness`**.
