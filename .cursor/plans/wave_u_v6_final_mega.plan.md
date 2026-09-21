---
name: Wave U V6 final MEGA
overview: "Single optimized Railway MEGA after V1–V5. OPS PINNED bump only if fully_qualified=true. Do not wait for V7/V8."
todos:
  - id: v6-preflight
    content: Newest tip pin; workspace backup; fieldbus vim-1; RAILWAY_ONLY before load_bench_env
    status: pending
  - id: v6-mega
    content: run_railway_hub_stress EXECUTE=1 full required gates including both 36
    status: pending
  - id: v6-ops-pinned
    content: BUG_REPORT + MILESTONES + AGENTS tip pins if FQ
    status: pending
isProject: false
---

# V6 — Single optimized final MEGA

**Parent:** [`wave_u_remainder_patch_cycles.plan.md`](wave_u_remainder_patch_cycles.plan.md)

## Purpose

Security/product FQ closeout for the tip that includes V1–V5. **Path migrate (V7) and compaction (V8) must not block OPS PINNED.**

## Recipe (bensbench, not Pi)

1. `./scripts/ghcr_newest_by_created.py` → pin one `sha-*` containing V1–V5 merges.
2. `./scripts/railway_central_workspace_backup.sh` → `~/openfdd-backups/railway/<UTC>/`.
3. Re-pin central → mqtt → web (image tag only); wait `/api/health`.
4. `./scripts/openfdd_fieldbus_railway_up.sh sha-<7>` with `OPENFDD_RAILWAY_EDGE_ID=vim-1`.
5. `RAILWAY_ONLY=1` **before** `load_bench_env`; refresh sticky `.env`; `OPENFDD_MCP_IMAGE` = same tip.
6. `./scripts/nightly-ot-bench/run_railway_hub_stress.sh` with `EXECUTE=1` `EXPECTED_EDGE_ID=vim-1` `OPENFDD_MQTT_ACL_EXECUTE=1`.
7. Require both gate **36**, 25/25b/26, 35, capacity; `fully_qualified=true` before OPS PINNED.
8. Update BUG_REPORT OPS PINNED + MILESTONES U-G + `AGENTS.md` + railway-cli skill.

## Exit

- Manifest `fully_qualified=true` artifact path cited; OPS PINNED bumped; or FAIL logged before fix (no greenwash).
