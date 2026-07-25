---
title: Job workspaces
parent: Architecture
nav_order: 11
---

# Job workspaces

**Status:** target contract. Filesystem layout lands in migration **PR1**.

A browser session is not the project database. `st.session_state` is not durable storage.

## Layout

```text
workspace/jobs/<job_id>/
  job.json
  mapping/
  configs/
  runs/
  findings/
  reports/
  wattlab/
  artifacts/
```

Telemetry stays in Feather / parquet (site historian). Jobs hold **pointers**, configs, run outputs, and findings — not SQLite historian tables.

## `job.json` (minimum)

```json
{
  "schema_version": 1,
  "job_id": "job-…",
  "job_name": "…",
  "site_name": null,
  "building_name": null,
  "status": "active",
  "created_at": "…",
  "updated_at": "…",
  "revisions": {
    "dataset": null,
    "mapping": null,
    "config": null,
    "engine": null
  }
}
```

## Lifecycle

Create · Open · Save · Duplicate · Rename · Archive · Delete (confirm) · Export/Import (later).

Stale results must not present as CURRENT when mapping/config/dataset revisions change.

See [VIBE19_VIBE20_OPENFDD_AUDIT.md](../migration/VIBE19_VIBE20_OPENFDD_AUDIT.md) §F–H.
