---
title: Job workspaces
parent: Architecture
nav_order: 11
---

# Job workspaces

**Status:** Milestone B complete — UI `job_store` + central `/api/jobs` (SoT when central is up).

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
| Store (thin client; central SoT when up) | [`services/ui/app/job_store.py`](../../services/ui/app/job_store.py) |
| Central API | [`services/central/src/jobs.rs`](../../services/central/src/jobs.rs) |
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

## Findings and dispositions (B6)

`findings/findings.json` holds machine evidence (SQL row hashes, rule outputs). Each finding requires `correlation_key` and `finding_id`. Dispositions live in `findings/dispositions.json` keyed by `correlation_key` — human status never overwrites evidence rows.

## WattLab (job-native SoT)

**Production source of truth** is job-native handoffs under `wattlab/handoffs/*.json`
(central `POST /api/jobs/{id}/wattlab/handoffs`, Streamlit helper
[`ui_wattlab_job.py`](../../services/ui/app/ui_wattlab_job.py)). Zip dumps from Export
remain **additive** for offline / vibe20 / backup — they do not replace the job
manifest. External EnergyPlus run metadata (when queued) lands under
`wattlab/runs/*.json`; central tracks status/artifacts only.

## Atomicity

Metadata writes use temp file + fsync + rename.

## Related

- [Milestone A closeout](../migration/MILESTONE_A_CLOSEOUT.md)
- Pandas inventory (UI lab vs production SQL): [PANDAS_USAGE_INVENTORY.md](PANDAS_USAGE_INVENTORY.md)
