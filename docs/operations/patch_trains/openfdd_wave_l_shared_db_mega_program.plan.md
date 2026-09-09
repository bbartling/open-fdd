---
name: Wave L 3.5 shared-DB mega
overview: "Wave L — shared database mega (3.5.0+). Cut over historian/jobs from volume-local Feather/Parquet-only to a shared DB with dual-write/migrate, DataFusion still for FDD SQL, React unchanged. Starts only after Wave K 3.4.0 pin CLOSED. Low-RAM one agent; phased PRs; ONE stress per shippable sub-rev."
todos:
  - id: l0-hygiene
    content: L0 — Hygiene START after 3.4.0 pin green
    status: pending
  - id: l1-engine-choice
    content: L1 — Lock engine (default Postgres) + schema v1 from Wave K ADR; spike connectivity in central
    status: pending
  - id: l2-dual-write
    content: L2 — Dual-write ingest + package import to Feather AND shared DB; feature flag
    status: pending
  - id: l3-read-path
    content: L3 — Historian/query + FDD register path can read shared DB (or Parquet export from DB) with provenance
    status: pending
  - id: l4-jobs-meta
    content: L4 — Jobs/findings metadata in shared DB (optional same rev or 3.5.1)
    status: pending
  - id: l5-migrate-tool
    content: L5 — Offline migrate workspace historian → shared DB + verify row counts
    status: pending
  - id: l6-cutover
    content: L6 — Flag default ON for shared DB; Feather remains backup/export
    status: pending
  - id: l7-stress
    content: L7 — tip pin + ONE full stress; BUG_REPORT Wave L CLOSED / 3.5.x
    status: pending
  - id: deferred-multivendor
    content: Multivendor Stage C (identity/MFA/tenant) — AFTER shared DB baseline
    status: pending
isProject: false
---

# Wave L — Shared database mega (3.5.x)

**Depends on:** Wave K **3.4.0 PINNED** ([`wave_k_340_filesystem_pin_master.plan.md`](wave_k_340_filesystem_pin_master.plan.md)).

**Problem:** Today the product historian is **volume-local** Feather under `/workspace` (+ Parquet trees for FDD). That blocks multi-instance hub, shared analytics across replicas, and clean multivendor tenancy. Operator wants **shared DB** ASAP after a frozen 3.4.0 pin.

## Product contract (unchanged)

- Central Rust + DataFusion SQL FDD + React SPA + Mosquitto + fieldbus  
- **No** product Python/pandas  
- Shared DB is **storage**, not a second FDD engine  

## Target architecture (sketch — lock in L1)

```text
fieldbus/MQTT/CSV → central ingest
       ├─ (3.4) Feather partitions on volume
       └─ (3.5) dual-write → shared DB (Postgres default)
                    ↓
            DataFusion (Scan / foreign table / Parquet export)
                    ↓
            /api/fdd/run · /api/analytics/* · SPA
```

| Decision | Default (override in L1 ADR amend) |
|----------|--------------------------------------|
| Engine | **Postgres 16** (Railway plugin or external) |
| Grain | site/building/equipment/point + timestamp UTC |
| Tenancy prep | `tenant_id` / `site_id` columns now; Stage C auth later |
| Rollback | Feature flag → Feather-only; 3.4.0 images remain pin |
| FDD | Keep `sql_rules/` DataFusion; do not rewrite rules in SQL dialect of PG |

## Phasing (VERSION)

| Rev | Concern |
|-----|---------|
| **3.5.0** | Engine wiring + dual-write + read flag OFF by default |
| **3.5.1** | Read path ON for historian/query canary building |
| **3.5.2** | Migrate tool + cutover default ON + stress |

One concern per PR. Mid-wave smoke. Full stress at each shippable pin the operator treats as deployable.

## Out of scope

- Browser→Mosquitto WebSockets  
- Full multivendor MFA/tenant isolation (Stage C)  
- Deleting Feather backup path in 3.5.0  
- Pandas cookbook deletion  

## Acceptance (Wave L CLOSED)

- Shared DB is source of truth for live historian on tip (or documented dual with read preference)  
- Migration from a 3.4.0 backup verified  
- Stress `fully_qualified=true` on tip; gate 09 still green  
- BUG_REPORT pin line **3.5.x**; Wave K 3.4.0 retained as rollback pin  
- Multivendor Stage C unblocked as **next** program (not this wave)
