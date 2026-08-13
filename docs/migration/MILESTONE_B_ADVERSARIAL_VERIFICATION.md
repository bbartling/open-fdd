---
title: Milestone B adversarial verification
parent: Migration
nav_order: 23
---

# Milestone B adversarial verification (C0)

**Date:** 2026-07-28  
**Open-FDD tip under test:** `5005ddd8` (+ C0 recovery/tests PR)

Statuses: `VERIFIED` | `PARTIALLY_VERIFIED` | `IMPLEMENTED_UNTESTED` | `NOT_IMPLEMENTED` | `DEFERRED`

| Capability | Status | Evidence |
|------------|--------|----------|
| Create Job via central | VERIFIED | `jobs_api_integration` + unit create |
| List Job | VERIFIED | API IT + `list_jobs` unit |
| Update with correct revision | VERIFIED | PATCH success in API IT |
| Reject stale revision | VERIFIED | PATCH 409 in API IT + unit |
| Duplicate Job | PARTIALLY_VERIFIED | unit + route; no dedicated HTTP IT yet |
| Archive / restore | VERIFIED | API IT + unit |
| Create run | VERIFIED | API IT + unit |
| Persist SUCCESS/FAILED run | VERIFIED | `update_run_status` + PATCH run |
| Survive central restart (meta) | VERIFIED | FS store; jobs remain on disk |
| Interrupted RUNNING recovery | VERIFIED | `recover_interrupted_runs` on startup; unit test |
| Write findings | VERIFIED | API IT + unit |
| Write dispositions | VERIFIED | API IT + unit |
| Correlate findings | PARTIALLY_VERIFIED | `correlation_key` required; no multi-run join suite |
| WattLab handoff | VERIFIED | API IT + unit write |
| Reject invalid handoff | PARTIALLY_VERIFIED | non-object rejected; schema soft |
| Evaluate stale + exact reason | VERIFIED | `STALE_MAPPING` unit + API IT |
| Isolate corrupt Job | VERIFIED | `list_jobs` skips bad JSON (Python + Rust list) |
| Reject path traversal / bad IDs | VERIFIED | `validate_job_id` + API GET bad id |
| Unauthorized API (JWT on) | VERIFIED | API IT 401 when `OPENFDD_JWT_SECRET` set |
| Missing/corrupt result artifacts | PARTIALLY_VERIFIED | malformed findings JSON → Invalid; deeper artifact suite deferred |
| React when central down | VERIFIED | `test_jobs_central_client.py` FS fallback |
| Run/result lineage | PARTIALLY_VERIFIED | `latest_run_id` + run.json; full artifact graph deferred |

## Policy locks (C0)

- Interrupted `RUNNING` → `FAILED` with restart message; **no auto-rerun**.
- JWT optional: when secret unset, anonymous admin (dev); when set, Bearer required for `/api/jobs*`.

## Residual / deferred to Milestone C+

- Browser Playwright jobs soak
- vibe20 WattLab dump v2/v3 compatibility matrix
- Deep symlink escape containment beyond ID regex + canonicalize
