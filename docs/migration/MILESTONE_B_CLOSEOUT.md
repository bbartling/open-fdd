---
title: Milestone B closeout
parent: Migration
nav_order: 21
---

# Milestone B closeout

**Date:** 2026-07-28

## Executive summary

Milestone B delivers persistent engineering Jobs with provenance fingerprints,
run records, stale detection, findings files, WattLab handoff manifests, and a
Streamlit Jobs UI that prefers central `/api/jobs` (filesystem fallback).

Milestone A was closed with residuals in [`MILESTONE_A_CLOSEOUT.md`](MILESTONE_A_CLOSEOUT.md).

## Architecture delivered

| Layer | Implementation |
|-------|----------------|
| Contract | [`docs/architecture/job-workspaces.md`](../architecture/job-workspaces.md) + UI `job_store` |
| Central SoT | `services/central/src/jobs.rs` + `/api/jobs*` routes |
| UI | `ui_jobs.py` + `central_client` jobs helpers |
| Provenance | Canonical JSON fingerprint (order-insensitive) |
| Runs / stale | `runs/<run_id>/run.json` + `/stale` endpoint |
| Findings | `findings/findings.json` via `job_store.save_findings` |
| WattLab | Job-native `wattlab/handoffs/*.json` |

## API endpoints

```text
GET/POST  /api/jobs
GET/PATCH /api/jobs/{job_id}
POST      /api/jobs/{job_id}/duplicate
POST      /api/jobs/{job_id}/archive
POST      /api/jobs/{job_id}/restore
POST      /api/jobs/{job_id}/runs
GET       /api/jobs/{job_id}/runs/{run_id}
POST      /api/jobs/{job_id}/runs/{run_id}/stale
GET/PUT   /api/jobs/{job_id}/findings
GET/PUT   /api/jobs/{job_id}/dispositions
POST      /api/jobs/{job_id}/wattlab/handoffs
```

## Cookbook preservation

Dual cookbooks unchanged; ownership CI + cookbook-parity remain green.

## Known limitations / Milestone C

- Full findings disposition UI and audit history UX
- Report PDF attachment wiring to Job folders
- Deeper Streamlit restore of all session knobs
- Replace DefaultHasher was replaced with SHA-256 in central fingerprints
- Interrupted RUNNING recovery policy (mark STALE/FAILED on restart) — partial
- Playground GHCR retirement still deferred
- `open_fdd.contracts` still deferred from Milestone A residuals

## Merged PRs

| PR | Scope |
|----|-------|
| [#583](https://github.com/bbartling/open-fdd/pull/583) | B0 — Milestone A closeout audit + ownership CI |
| [#584](https://github.com/bbartling/open-fdd/pull/584) | B1 — Job filesystem contract + tests |
| [#585](https://github.com/bbartling/open-fdd/pull/585) | B2–B8 — central `/api/jobs`, runs, stale, UI client |
| _(B6/B9 closeout PR)_ | Findings/dispositions API, stale banner, acceptance |

**Tip SHA (post #585):** `9f53792e836981bd236114681c5b67a432de3552`
