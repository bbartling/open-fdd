---
title: Milestone D acceptance
parent: Migration
nav_order: 34
---

# Milestone D acceptance

**Date:** 2026-07-28 · Branch `milestone-d/d5-closeout`

Honest acceptance for D0–D5. Full Milestone D / Phase 8
(`sha-*` Job → SQL FDD → DF analytics → finding → WattLab → E+ attach → restart)
is **not** claimed complete.

## Automated evidence

| Check | Command / evidence | Result |
|-------|-------------------|--------|
| D1 historian / analytics | `cargo test -p openfdd-central analytics` | Required green |
| D4 eplus policy + queue | `cargo test -p openfdd-central eplus` | Required green |
| Clippy | `cargo clippy -p openfdd-central -- -D warnings` | Required clean |
| Ownership | `python3 scripts/architecture_ownership_check.py` | Required green |
| D2 mutation | `python3 scripts/rule_parity_mutation_check.py` | Required green |
| D3 handoff shape | `pytest services/ui/app/test_wattlab_job_handoff.py` | Required green |
| Full-stack `sha-*` | Operator / GHCR after merge | **Not claimed** |

## Slice acceptance

| Slice | Bar on this branch |
|-------|--------------------|
| D2 | Registry ≥ 63; dual cookbooks ≥ 59 headings; high-risk keywords; missing cookbook path fails |
| D3 | Payload has `source=job_native`, `kind=wattlab_handoff`; central create mocked |
| D4 | Invalid digest / path escape / root runner rejected; QUEUED JSON under `wattlab/runs/` |
| D5 | No production `Vite :5173` develop hint in edge dev_stack; docs closeout honest |

## Manual / deferred

1. External runner claims QUEUED eplus runs and attaches artifact hashes.
2. BUILDING_100 multi-rule parity evidence beyond fixtures.
3. Publish GHCR `sha-<tip>` and run Job → handoff → optional E+ queue soak.

| Field | Value |
|-------|-------|
| open-fdd tip (pre-D5) | `e5bd0ffd` |
| playground | `d553e31` |
| Notes | Focused PRs #590–#593; D5 is docs/escape-hatch closeout |
