---
name: Wave U V7 tenant path migrate
overview: "Backup-first dual-read + additive migrate hub-root building=* to tenants/{tid}/…. Soft-OPEN wave-o1-tenant-path-migrate. After V6."
todos:
  - id: v7-backup-inventory
    content: Railway workspace backup; inventory building=* vs tenants/*
    status: pending
  - id: v7-dual-read-migrate
    content: Dual-read + additive migrate ACME/B100/LAKESIDE; permanent ACL regressions
    status: pending
  - id: v7-smoke
    content: Smoke FDD on migrated buildings; targeted gates if ingest/ACL contracts change
    status: pending
isProject: false
---

# V7 — `wave-o1-tenant-path-migrate`

**Parent:** [`wave_u_remainder_patch_cycles.plan.md`](wave_u_remainder_patch_cycles.plan.md)  
**Prior notes:** Wave P `p3-tenant-path-*` in residual stress plan.

## Soft-OPEN closed by this cycle

- `wave-o1-tenant-path-migrate`

## Work

1. **Hard gate:** `./scripts/railway_central_workspace_backup.sh` before any migrate.
2. Inventory hub-root `building=*` vs any `tenants/{tid}/…` on hub volume.
3. Dual-read: prefer `tenants/{tid}/…` when present; fall back to hub-root.
4. Additive copy (not delete) for ACME / BUILDING_100 / LAKESIDE_ES (or fixtures).
5. Same `building_id` under two tenants isolates via path namespace.
6. Permanent regressions: foreign tenant deny; hub_admin sees all.
7. Smoke: health, edges, FDD on migrated buildings. **No full MEGA** unless ingest/ACL contracts change — then gates 20/25/25b + inventory only.

## Exit

- Migrate evidence + parity artifact paths in BUG_REPORT; Soft-OPEN CLOSED.
