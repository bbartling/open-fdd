---
name: Wave K 3.4.0 filesystem pin
overview: "Wave K — pin Open-FDD 3.4.0 as the last qualified filesystem-historian baseline (Feather/Parquet on volume), wrap BUG_REPORT residuals for handoff, land shared-DB ADR + inventory only. ONE full stress. Then Wave L 3.5 shared-DB mega ASAP. Low-RAM one agent."
todos:
  - id: k0-hygiene
    content: K0 — GH hygiene START (0 PRs/branches; tip Actions green; ops pin sha-c1b1aa5 or tip)
    status: pending
  - id: k1-version-340
    content: K1 — VERSION bump 3.3.41 → 3.4.0 + Cargo pins (baseline pin rev)
    status: pending
  - id: k2-historian-freeze-docs
    content: K2 — Freeze historian contract docs (paths, backup/restore, Railway volume, no silent format change)
    status: pending
  - id: k3-shared-db-adr-inventory
    content: K3 — ADR + machine-readable inventory for shared DB (engine options, dual-write, tenancy hooks) — design only
    status: pending
  - id: k4-residual-782
    content: K4 — #782 MQTT SSE — ship small OR explicit PARK with owner (do not block 3.4.0 pin)
    status: pending
  - id: k5-stress-340
    content: K5 — tip Publish → Railway backup+re-pin → ONE run_railway_hub_stress.sh → fully_qualified
    status: pending
  - id: k6-bug-report-closed
    content: K6 — BUG_REPORT Wave K CLOSED / 3.4.0 pin line; handoff to Wave L
    status: pending
  - id: deferred-wave-l
    content: Wave L 3.5 shared-DB mega — AFTER 3.4.0 pin (see wave_l_shared_db_mega_master)
    status: pending
isProject: false
---

# Wave K — 3.4.0 filesystem-historian pin (master)

**Active program** after Wave J **CLOSED** (`sha-c1b1aa5` / 3.3.41 · stress `20260909T010712Z` · `fully_qualified=true`).

**Retired:** [`wave_j_df_boundary_master.plan.md`](wave_j_df_boundary_master.plan.md) — historical only.

**Why 3.4.0 (not another 3.3.x):** Operator wants a **pinned baseline** before the shared-database mega. 3.4.0 = last fully qualified **volume-local Feather/Parquet** product line. 3.5.x = shared DB cutover.

**Law:** Low-RAM one agent. No local stack `docker build`. 0 open PRs / stale branches / failed tip Actions at child start/end. Mid-wave = smoke only. **ONE** full `run_railway_hub_stress.sh` at **K5**.

## Non-goals (this wave)

- Implementing Postgres/shared DB runtime (→ Wave L)
- Multivendor identity/MFA/tenant isolation Stage C (after shared DB exists)
- Reopening PARKED `sql-anomaly-screening` or ABANDONED hybrid ML
- Mass Dependabot merges (hygiene close only)

## Order

```mermaid
flowchart TD
  K0[K0 hygiene]
  K1[K1 VERSION 3.4.0]
  K2[K2 historian freeze docs]
  K3[K3 shared-DB ADR + inventory]
  K4[K4 optional 782]
  K5[K5 ONE stress]
  K6[K6 BUG_REPORT pin]
  L[Wave L 3.5 shared DB]
  K0 --> K1
  K1 --> K2
  K2 --> K3
  K3 --> K4
  K4 --> K5
  K3 --> K5
  K5 --> K6
  K6 --> L
```

| Step | Concern | VERSION? | Images? |
|------|---------|----------|---------|
| **K0** | 0 PRs; tip GHCR green | no | tip Publish if docs tip incomplete |
| **K1** | Bump **3.4.0** | yes | after merge |
| **K2** | Document freeze: `/workspace` Feather+Parquet, backup script, restore rules | docs ok in same or follow PR | no if docs-only |
| **K3** | ADR + YAML inventory (engine, schema sketch, dual-write plan, rollback) | no | no |
| **K4** | [#782](https://github.com/bbartling/open-fdd/issues/782) SSE — ship **or** PARK | if product | if product |
| **K5** | Backup → re-pin → fieldbus → full stress | — | tip sha |
| **K6** | BUG_REPORT **3.4.0 PINNED** + Wave L OPEN | docs | — |

## Acceptance (Wave K CLOSED / 3.4.0 pin)

- Health `3.4.0+<sha>` on Railway; GHCR tip complete; Python-absence PASS
- Stress `fully_qualified=true` citing **this** tip only
- Historian freeze docs + shared-DB ADR merged (design, not runtime)
- BUG_REPORT header: **PINNED 3.4.0** · Next = Wave L shared DB
- #782 either CLOSED or PARKED with explicit owner — never “done by docs alone”

## Child plans

| Order | Plan |
|-------|------|
| K0–K6 | this master |
| L | [`wave_l_shared_db_mega_master.plan.md`](wave_l_shared_db_mega_master.plan.md) |
| Optional | [`mqtt_monitor_sse_782.plan.md`](mqtt_monitor_sse_782.plan.md) as K4 |
