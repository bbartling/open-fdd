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

Adversarial verification: [`MILESTONE_B_ADVERSARIAL_VERIFICATION.md`](MILESTONE_B_ADVERSARIAL_VERIFICATION.md).

## Architecture delivered

| Layer | Implementation |
|-------|----------------|
| Contract | [`docs/architecture/job-workspaces.md`](../architecture/job-workspaces.md) + UI `job_store` |
| Central SoT | `services/central/src/jobs.rs` + `/api/jobs*` routes |
| UI | `ui_jobs.py` + `central_client` jobs helpers |
| Provenance | Canonical JSON fingerprint (order-insensitive) |
| Runs / stale | `runs/<run_id>/run.json` + `/stale` + PATCH run status |
| Findings | `findings/findings.json` via central + `job_store` |
| WattLab | Job-native `wattlab/handoffs/*.json` |
| Restart recovery | Interrupted `RUNNING` → `FAILED` on central startup |

## API endpoints

```text
GET/POST  /api/jobs
GET/PATCH /api/jobs/{job_id}
POST      /api/jobs/{job_id}/duplicate
POST      /api/jobs/{job_id}/archive
POST      /api/jobs/{job_id}/restore
POST      /api/jobs/{job_id}/runs
GET/PATCH /api/jobs/{job_id}/runs/{run_id}
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
- Browser Playwright jobs soak
- Playground GHCR retirement still deferred
- `open_fdd.contracts` still deferred from Milestone A residuals

## Merged PRs

| PR | Scope |
|----|-------|
| [#583](https://github.com/bbartling/open-fdd/pull/583) | B0 — Milestone A closeout audit + ownership CI |
| [#584](https://github.com/bbartling/open-fdd/pull/584) | B1 — Job filesystem contract + tests |
| [#585](https://github.com/bbartling/open-fdd/pull/585) | B2–B8 — central `/api/jobs`, runs, stale, UI client |
| [#586](https://github.com/bbartling/open-fdd/pull/586) | B6/B9 — findings/dispositions API, stale banner, acceptance |
| C0 | Adversarial verification + RUNNING recovery + jobs API IT |

**Tip SHA (post #586):** `5005ddd8` (C0 PR advances tip).
