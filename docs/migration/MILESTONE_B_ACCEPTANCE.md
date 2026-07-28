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
| Job store unit tests | `pytest services/ui/app/test_job_store.py` | 13 passed (B1) |
| Central jobs unit tests | `cargo test -p openfdd-central jobs::` | 5 passed |
| Architecture ownership | `python3 scripts/architecture_ownership_check.py` | OK |
| Cookbook docs | `cookbook_parity_check.py --docs-only` | PASS |

## Manual / stack acceptance (operator)

Use nightly / immutable `sha-*` per `openfdd_agent_spec/CONTAINER_AGENT.md`:

1. Pull/start CSV or standalone stack with `OPENFDD_IMAGE_TAG=sha-<tip>`.
2. Open Streamlit UI → Jobs expander → create Job.
3. Save mapping → create run via API (or subsequent UI wiring) with fingerprint components.
4. Confirm `workspace/jobs/<id>/` contains `job.json`, `datasets/`, `runs/`.
5. Change `mapping_revision` in fingerprint → `/stale` returns `STALE_MAPPING`.
6. Restart containers → reopen Job (list/get still works).
7. Write findings + WattLab handoff via `job_store` helpers; confirm files under job dir.
8. Confirm both expression cookbooks still build on Pages.

Record tip SHA and image digests here when the acceptance run is executed on a live stack:

| Field | Value |
|-------|-------|
| Open-FDD SHA | _(fill on live run)_ |
| `openfdd-ui` digest | _(fill)_ |
| `openfdd-central` digest | _(fill)_ |
| Notes | Automated unit/API tests green in CI; full browser restart soak = operator confirmation |

## GitHub Actions

Required checks on Milestone B PRs must be green before merge (Rust Stack CI,
Streamlit UI, Cookbook parity, Docs, AppSec).
