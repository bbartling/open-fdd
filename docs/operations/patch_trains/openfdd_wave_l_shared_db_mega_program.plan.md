---
name: Wave L multi-client shared hosting
overview: "ACTIVE — Wave L 3.5.x. L4 LIVE ops sha-d67d27b / 3.5.3. L5 next (budgets). Low-RAM; Actions green; 0 stale after merge. L8 = enhanced stress + 3.5.x PINNED."
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
    content: L2 — #894 MERGED; tip sha-2dea571; gates 11+12 PASS; mode OFF LIVE
    status: completed
  - id: l3-mqtts-isolation
    content: L3 — #899 MERGED; tip sha-be65366; gates 11+12+13 PASS; mode OFF LIVE
    status: completed
  - id: l4-ui-domains
    content: L4 — #901 MERGED; tip sha-d67d27b; gates 11–14 PASS; mode OFF LIVE
    status: completed
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
    content: L8 — ENHANCED full stress (00–14+ A↔B) + BUG_REPORT 3.5.x PINNED; mode OFF
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

## Where we are (2026-09-11) — **ACTIVE**

| Item | State |
|------|--------|
| **Program** | **ACTIVE** — Wave L **3.5.x** |
| **Gate L0** | **DONE** — Wave K **3.4.0 PINNED** (`sha-9c3e8b1`) |
| **Phase-0 ADR** | **DONE** (#885) — `docs/architecture/ADR_multi_client_shared_hosting.md` |
| **L1** | **DONE** — #891 · tip **`sha-a11b6cb`** · health **`3.5.0+a11b6cb181fc`** · gate 11 PASS · `multi_tenant=false` |
| **L2** | **DONE** — #894 product **`sha-2dea571`** · ops tip **`sha-af08ac7`** (#897 flake-fix) · health **`3.5.1+af08ac7b9889`** · gates **11+12 PASS** |
| **L3** | **DONE** — #899 · tip **`sha-be65366`** · health **`3.5.2+be65366316bb`** · gates **11+12+13 PASS** · `multi_tenant=false` |
| **L4** | **DONE** — #901 · tip **`sha-d67d27b`** · health **`3.5.3+d67d27b9e791`** · gates **11–14 PASS** · `multi_tenant=false` · `active_tenant_id=legacy` |
| **Ops pin** | **`sha-d67d27b`** (rollback **`sha-9c3e8b1`** / 3.4.0; prior L3 **`sha-be65366`**) |
| **Step** | **L5** — Per-tenant budgets + noisy-neighbor lab notes |

### Progress board

```text
[x] L0 / L0b / L0c  pin + BUG_REPORT carry + hygiene law
[x] Phase-0 ADR (#885)
[x] L1  Control plane OFF + TenantContext + gate 11 (#891 / sha-a11b6cb)
[x] L2  Tenant Parquet + DF + gate 12 (#894 / ops sha-af08ac7)
[x] L3  MQTTS namespace + ACL (#899 / sha-be65366)
[x] L4  Tenant UI/session (#901 / sha-d67d27b)   ← DONE
[ ] L5  Per-tenant budgets   ← YOU ARE HERE
[ ] L6–L7 …
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
| Full stress | **Not** every tip. Mid-wave = smoke (+ gates **11–14**). **ONE enhanced full stress at L8**. |
| Tip noise | Cancelled/incomplete Publish on non-tip SHAs is noise — judge **latest tip** checks only. Early tip-completeness red before Publish completes is noise. |
| Logging | Every pin/smoke/stress/migrate → [`BUG_REPORT_OT_MODBUS_HAYSTACK.md`](../BUG_REPORT_OT_MODBUS_HAYSTACK.md). Mid-wave: tip/smoke + gates 11–14; **PINNED only at L8**. |

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
   - **12** Parquet isolation
   - **13** MQTTS namespace
   - **14** Tenant UI/session
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
| **1** | **3.5.0** | Control plane + TenantContext; **OFF** | **DONE** smoke + gate 11 |
| **2** | **3.5.1** | Tenant Parquet + DF | **DONE** smoke + gates 11–12 |
| **3** | **3.5.2** | MQTTS ACL | **DONE** smoke + gates 11–13 |
| **4** | **3.5.3** | UI membership | **DONE** smoke + gates 11–14 |
| 5 | 3.5.4 | Budgets | lab notes |
| 6 | 3.5.5 | ZAP/AF + isolation harness | Tier-2 |
| 7–8 | 3.5.x | Migrate dry-run + **L8 enhanced** | full 00–14+ |

## Out of scope

Postgres historian · Feather↔DB TS · #782 browser→Mosquitto WS · live migrate/DNS without operator · OT expansion

## Acceptance (Wave L CLOSED)

- Tier-2 A↔B isolation evidence  
- Single-tenant default works; **3.4.0** rollback retained  
- Mode **OFF** until operator checklist  
- Enhanced L8 `fully_qualified=true`; BUG_REPORT **3.5.x PINNED**  
