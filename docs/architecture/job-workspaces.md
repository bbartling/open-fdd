---
title: Job workspaces
parent: Architecture
nav_order: 11
---

# Job workspaces

**Status:** Milestone B1 filesystem contract (UI `job_store`; central `/api/jobs` in B2).

A browser session is not the project database. `st.session_state` is not durable storage.

## Layout

```text
workspace/jobs/<job_id>/
  job.json
  mapping/
    role_map.json
    equipment_map.json
  configs/
    session_config.json
    rule_parameters.json
    schedules.json
  datasets/
    dataset_refs.json
  runs/
    <run_id>/
      run.json
      …
  findings/
    findings.json
    dispositions.json
  reports/
  wattlab/
    handoffs/
    runs/
  artifacts/
```

Telemetry stays in Feather / parquet (site historian). Jobs hold **pointers**, configs, run outputs, and findings — not full historian copies.

## Identifiers

| Kind | Pattern |
|------|---------|
| Job | `job-<uuid>` |
| Run | `run-<uuid>` |
| Finding | `finding-<uuid>` (B6) |

## Implementation

| Piece | Path |
|-------|------|
| Store (interim SoT until B2/B7) | [`services/ui/app/job_store.py`](../../services/ui/app/job_store.py) |
| Streamlit entry | [`services/ui/app/ui_jobs.py`](../../services/ui/app/ui_jobs.py) |
| Tests | `services/ui/app/test_job_store.py` |

## `job.json` (schema_version 1)

```json
{
  "schema_version": 1,
  "job_id": "job-…",
  "job_name": "Building 100 RCx Study",
  "description": "",
  "status": "active",
  "archived": false,
  "created_at": "",
  "updated_at": "",
  "created_by": "",
  "site_id": "",
  "site_name": null,
  "building_name": null,
  "tags": [],
  "meta_revision": "<opaque>",
  "latest_run_id": null,
  "latest_findings_revision": null,
  "mapping_path": null,
  "revisions": {
    "dataset": null,
    "mapping": null,
    "config": null,
    "engine": null
  }
}
```

`meta_revision` enables optimistic concurrency: writers must pass the revision they read; stale writes raise `revision_conflict`.

## Lifecycle

Create · List (active/archived/filters) · Get · Update · Duplicate · Archive · Restore · Delete (confirm only).

Duplicate copies mapping/config/dataset_refs — **not** runs, findings, or reports.

## Atomicity

Metadata writes use temp file + fsync + rename.

## Related

- [Milestone A closeout](../migration/MILESTONE_A_CLOSEOUT.md)
- Pandas inventory (UI lab vs production SQL): [PANDAS_USAGE_INVENTORY.md](PANDAS_USAGE_INVENTORY.md)
