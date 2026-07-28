---
title: Milestone B acceptance
parent: Migration
nav_order: 22
---

# Milestone B acceptance

**Date:** 2026-07-28

## Automated evidence

| Check | Command / evidence | Result |
|-------|-------------------|--------|
| Job store unit tests | `pytest services/ui/app/test_job_store.py` | 14 passed |
| Central jobs unit tests | `cargo test -p openfdd-central jobs::` | includes recovery |
| Jobs API integration | `cargo test -p openfdd-central --test jobs_api_integration` | C0 |
| Central-down UI client | `pytest services/ui/app/test_jobs_central_client.py` | C0 |
| Architecture ownership | `python3 scripts/architecture_ownership_check.py` | OK |
| Cookbook docs | `cookbook_parity_check.py --docs-only` | PASS |
| Adversarial matrix | [`MILESTONE_B_ADVERSARIAL_VERIFICATION.md`](MILESTONE_B_ADVERSARIAL_VERIFICATION.md) | C0 |

## Manual / stack acceptance (operator)

Use nightly / immutable `sha-*` per `openfdd_agent_spec/CONTAINER_AGENT.md`:

1. Pull/start CSV or standalone stack with `OPENFDD_IMAGE_TAG=sha-<tip>`.
2. Open Streamlit UI → Jobs expander → create Job.
3. Save mapping → create run via API with fingerprint components; PATCH to RUNNING then SUCCEEDED.
4. Confirm `workspace/jobs/<id>/` contains `job.json`, `datasets/`, `runs/`.
5. Change `mapping_revision` in fingerprint → `/stale` returns `STALE_MAPPING`.
6. Restart containers → reopen Job; any leftover RUNNING run is FAILED with restart note.
7. Write findings + WattLab handoff; confirm files under job dir.
8. Confirm both expression cookbooks still build on Pages.

| Field | Value |
|-------|-------|
| Open-FDD SHA | `5005ddd8` (+ C0 PR tip after merge) |
| `openfdd-ui` digest | `ghcr.io/bbartling/openfdd-ui:sha-<tip>` after GHCR publish |
| `openfdd-central` digest | `ghcr.io/bbartling/openfdd-central:sha-<tip>` after GHCR publish |
| Notes | Adversarial unit/API IT green; full browser soak remains operator confirmation |

## GitHub Actions

Required checks on Milestone B/C0 PRs must be green before merge (Rust Stack CI,
Streamlit UI, Cookbook parity, Docs, AppSec).
