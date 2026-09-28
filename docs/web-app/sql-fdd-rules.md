---
title: SQL FDD Rules tab
parent: Web App
nav_order: 4
---

# SQL FDD Rules tab

Route: **`/sql-fdd`** (Integrations sidebar).

## UX (3.2.6+)

Professional commissioning surface — no NL prompt or visual query builder:

| Control | Purpose |
|---------|---------|
| **Historian table** | `telemetry_pivot` (default) or `telemetry` |
| **Equipment scope** | Haystack `equip:*` id for `WHERE equipment_id = …` |
| **SQL editor** | Read-only DataFusion `SELECT` |
| **Format SQL** | Keyword layout only |
| **Validate / Run** | Syntax check and test against historian |

## Default example

Replace `equip:local-test-equipment` with a real Haystack equipment id from your site (Model tab or `GET /api/model/sites/{site}/equipment`).

```sql
SELECT
  timestamp,
  equipment_id,
  oa_t,
  CASE
    WHEN oa_t IS NULL THEN false
    WHEN oa_t < 40.0 THEN true
    WHEN oa_t > 110.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:local-test-equipment'
```

## Multi-sensor rules

List every historian column in the rule’s `required_inputs` array (e.g. `oa_t`, `zn_t`). The dashboard fault modal shows **per-sensor** averages in-alarm vs normal when multiple inputs are bound.

## Data location

Historian pivot files: `workspace/data/historian/validation/telemetry_pivot.jsonl` (+ Arrow IPC snapshot). See [Storage & DataFusion]({{ site.baseurl }}/architecture/storage-and-datafusion.html).

## Results, Overview, and HITL scope

All registry and site-defined rule results appear under **Data Model → Results
by category** and in the FDD results API. Overview health matrices intentionally
remain fixed engineering summaries for the shipped AHU, plant, heat-pump, VAV,
zone, and sensor families. The registry field `dashboard_wired` records that a
shipped rule contributes to one of those maintained summaries; it does not
dynamically create an Overview panel for a custom rule.

Engineering findings HITL is job-scoped. It becomes actionable only after a job
has produced findings and stores dispositions through the job dispositions API.
Bulk FDD results do not implicitly create HITL findings; when no jobs or findings
exist, the UI explains that state and leaves bulk results in Results by category.
