---
title: Storage & DataFusion
parent: Architecture
nav_order: 3
---

# Storage & DataFusion

## Apache Arrow / Feather historian

Telemetry is stored as **columnar Feather** partitions under `workspace/data/historian/`. The bridge writes Arrow RecordBatches from driver polls and CSV imports.

Benefits at the edge:

- Efficient columnar scans for trend plots and SQL rules
- No external database server required
- Portable files for backup and offline analysis

Query via REST:

- `GET/POST /api/historian/query`
- `GET /api/timeseries/readings`
- Dashboard **Plots** tab

## DataFusion SQL

Fault detection rules are **DataFusion SQL** statements executed against historian tables. See the [**Rule Cookbook**]({{ site.baseurl }}/rules/cookbook/) for full HVAC patterns.

API highlights:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/rules` | List active rules |
| POST | `/api/rules/save` | Save rule SQL |
| POST | `/api/fdd/run` | Execute FDD run |
| POST | `/api/fdd-rules/{id}/activate` | Activate rule |

Rules bind to Haystack point semantics through the assignment graph — configure assignments before expecting meaningful FDD output.

## Data management

The **Historian storage** tab (`/data-management`) inspects partitions and supports purge-by-source with preview/execute gates. Export CSV before destructive purges.

See [DataFusion SQL Rules]({{ site.baseurl }}/rules/) for examples.
