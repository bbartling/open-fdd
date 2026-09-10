---
name: Wave L multi-client shared hosting
overview: "ACTIVE — Wave L 3.5.x. L1 LIVE sha-a11b6cb / 3.5.0 mode OFF. Low-RAM GH loop; Actions green + 0 stale PRs/branches. L2 next. L8 = enhanced full stress (00–11+) + BUG_REPORT 3.5.x PINNED."
todos:
  - id: l0-wait-k-pin
    content: L0 — Wave K 3.4.0 PINNED (sha-9c3e8b1 / stress 20260910T021557Z) — UNBLOCKED
    status: completed
  - id: l0b-bug-report-carry
    content: L0b — BUG_REPORT carry-in — no OPEN MEGAs; gate10 keep-green; #782+anomaly not Wave L
    status: completed
  - id: l0c-hygiene-law
    content: L0c — Low-RAM + GH hygiene law locked in plan (Actions green; 0 stale PRs/branches)
    status: completed
  - id: l1-control-plane
    content: L1 — #891 MERGED; tip sha-a11b6cb; gate 11 PASS; mode OFF LIVE
    status: completed
  - id: l2-parquet-isolation
    content: L2 — Tenant Parquet roots + DF providers (no shared-table WHERE)
    status: pending
  - id: l3-mqtts-isolation
    content: L3 — MQTTS namespace + ACL + identity provenance
    status: pending
  - id: l4-ui-domains
    content: L4 — Tenant UI/session; single domain first
    status: pending
  - id: l5-budgets
    content: L5 — Per-tenant budgets + noisy-neighbor lab notes
    status: pending
  - id: l6-qual-hardening
    content: L6 — ZAP/AF fixes + A↔B isolation harness + digest scans
    status: pending
  - id: l7-migrate-handoff
    content: L7 — Legacy-tenant migrate dry-run + operator checklist
    status: pending
  - id: l8-stress-pin
    content: L8 — ENHANCED full stress (00–11+ A↔B) + BUG_REPORT 3.5.x PINNED; mode OFF
    status: pending
  - id: deferred-stage-c
    content: IdP/MFA/dedicated SKUs — after shared-hosting baseline
    status: pending
  - id: deferred-782-sse
    content: Optional #782 MQTT monitor SSE — separate plan; never blocks Wave L
    status: pending
  - id: deferred-sql-anomaly
    content: sql-anomaly-screening PARKED — not Wave L shared-hosting
    status: pending
isProject: false
---

# Wave L — Multi-client shared hosting (3.5.x)

**Cursor SoT:** [`wave_l_shared_db_mega_master.plan.md`](../../../../.cursor/plans/wave_l_shared_db_mega_master.plan.md)  
**Depends on:** Wave K **3.4.0 PINNED** (`sha-9c3e8b1`). Phase-0 ADR in K3. Product coding after K pin.

## Where we are (2026-09-10) — **ACTIVE**

| Item | State |
|------|--------|
| **Program** | **ACTIVE** — Wave L **3.5.x** |
| **Gate L0** | **DONE** — Wave K **3.4.0 PINNED** |
| **Phase-0 ADR** | **DONE** (#885) — `docs/architecture/ADR_multi_client_shared_hosting.md` |
| **BUG_REPORT product OPEN** | **None** (L1 CLOSED; Wave K MEGAs CLOSED) |
| **Ops pin** | **`sha-a11b6cb`** / `3.5.0+a11b6cb181fc` · `multi_tenant=false` (rollback `sha-9c3e8b1`) |
| **Step** | **L2** — Tenant Parquet roots + DF providers |

### BUG_REPORT carry-in

| ID | Status | In Wave L? |
|----|--------|------------|
| Wave K MEGAs + plot-span | CLOSED | Keep green (gate 10 + L8) |
| #782 SSE | DEFERRED | **No** |
| sql-anomaly | PARKED | **No** |
| Stage C | after L8 | deferred-stage-c |

### Progress board

```text
[x] L0 / L0b / L0c  pin + BUG_REPORT carry + hygiene law
[x] Phase-0 ADR (#885)
[x] L1  Control plane OFF + TenantContext + gate 11 (#891 / sha-a11b6cb)
[ ] L2  Tenant Parquet + DF   ← YOU ARE HERE
[ ] L3–L7 …
[ ] L8  ENHANCED full stress + BUG_REPORT 3.5.x PINNED
```

---

## Law — low-RAM + GH hygiene (every PR)

| Rule | Do |
|------|----|
| Agents | **One** agent. No parallel heavy Task/subagents. |
| Builds | **Never** local `docker build` of central/web/mqtt/fieldbus. GHCR `sha-*` tip only. |
| Between tips | tip Publish → tip gate → backup → Railway re-pin hub+fieldbus → soak → **smoke** → **BUG_REPORT** |
| GH Actions | Every product PR: wait checks **green** before merge. No merge on red. |
| Branches / PRs | After merge: **0 open PRs**, remote **only `master`**, delete merged local branches. |
| Full stress | **Not** every tip. Mid-wave = smoke (+ gate **11** when present). **ONE enhanced full stress at L8**. |
| Tip noise | Cancelled/incomplete Publish on non-tip SHAs is noise — judge **latest tip** checks only. |
| Logging | Every pin/smoke/stress/migrate → [`BUG_REPORT_OT_MODBUS_HAYSTACK.md`](../BUG_REPORT_OT_MODBUS_HAYSTACK.md). Mid-wave: tip/smoke + gate 11; **PINNED only at L8**. |

### Qual tiers

| Tier | When | What |
|------|------|------|
| 1 Per PR | every product PR | authz unit/integration; AppSec; Rust CI |
| 2 Candidate | multi-tenant tip digests | A↔B storage/API/MQTT; ZAP tiers; restore |
| 3 Field | authorized Railway | smoke / freshness only — no OT DoS |

---

## L8 — Enhanced stress + BUG_REPORT (closeout)

**Required** for Wave L **CLOSED** / **3.5.x PINNED**:

1. Tip Publish complete (hub+fieldbus same `sha-<7>`)
2. `./scripts/check_ghcr_tip_stack.sh` **PASS**
3. Backup → Railway hub+fieldbus re-pin → health `3.5.x+…`
4. **ONE** `run_railway_hub_stress.sh` with **no `SKIP_ZAP`**, gates **at least**:
   - **00–10** (Wave K gate 10 MEGAs still green)
   - **11** Wave L tenant mode / control-plane smoke (`multi_tenant=false` until operator enable)
   - **12+** (from L6) synthetic **A↔B** isolation when mode exercised in lab
5. `qualification_manifest` → **`fully_qualified=true`**
6. Update BUG_REPORT: tip/pin, stress path, MEGA/isolation rows, **3.5.x PINNED**, Next = Stage C deferred
7. Hygiene: 0 open PRs / only `master` / Actions green on tip

Mode remains **OFF** in prod until operator checklist.

---

## What “shared DB” means (do not drift)

| Yes | No |
|-----|-----|
| Shared Railway hub, many firms | Postgres TS historian |
| Tenant-partitioned Parquet + scoped DF | UI `customer_id` filter alone |
| Metadata control plane | Feather↔DB telemetry dual-write |
| Flag **OFF** until Tier-2 | Public enable without operator auth |

## Architecture (ADR)

```text
control plane (tenants/users/memberships/buildings)
        + tenant-partitioned Parquet roots
        → DataFusion tenant-scoped providers
        → /api + MCP + jobs (TenantContext fail-closed)
        → MQTTS tenants/{tid}/buildings/{bid}/edges/{eid}/…
```

## Phases → VERSION

| Phase | Rev | Deliverable | Stress |
|-------|-----|-------------|--------|
| 0 | docs | ADR (done) | — |
| **1** | **3.5.0** | Control plane + TenantContext; **OFF** | smoke + gate 11 |
| 2 | 3.5.1 | Tenant Parquet + DF | A↔B storage |
| 3 | 3.5.2 | MQTTS ACL | MQTT clients |
| 4 | 3.5.3 | UI membership | smoke |
| 5 | 3.5.4 | Budgets | lab notes |
| 6 | 3.5.5 | ZAP/AF + isolation harness | Tier-2 |
| 7–8 | 3.5.x | Migrate dry-run + **L8 enhanced** | full 00–12+ |

## Out of scope

Postgres historian · Feather↔DB TS · #782 browser→Mosquitto WS · live migrate/DNS without operator · OT expansion

## Acceptance (Wave L CLOSED)

- Tier-2 A↔B isolation evidence  
- Single-tenant default works; **3.4.0** rollback retained  
- Mode **OFF** until operator checklist  
- Enhanced L8 `fully_qualified=true`; BUG_REPORT **3.5.x PINNED**  
