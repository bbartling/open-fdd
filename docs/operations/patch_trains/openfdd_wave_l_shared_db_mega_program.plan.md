---
name: Wave L multi-client shared hosting
overview: "Wave L (3.5.x) — multi-client shared hosting on Railway: tenant-partitioned Parquet/DataFusion + transactional control plane (metadata only). NOT Postgres time-series. Feature flag OFF until qualified. Phase 0 ADR during Wave K; product coding after 3.4.0 pin. Agent tests via Railway CLI + disposable qualification. Low-RAM refresh/smoke between builds; full stress + isolation/ZAP tiers per shippable pin."
todos:
  - id: l0-wait-k-pin
    content: L0 — Wait Wave K 3.4.0 PINNED; hygiene START; BUG_REPORT Active→Wave L (Phase0 ADR may land in K3)
    status: pending
  - id: l1-control-plane
    content: L1 — Tenant control plane (tenants/users/memberships/buildings/edges); TenantContext; flag OFF; Railway CLI smoke
    status: pending
  - id: l2-parquet-isolation
    content: L2 — Tenant-partitioned Parquet roots + DataFusion providers (no cross-tenant register+WHERE); cache/job scope
    status: pending
  - id: l3-mqtts-isolation
    content: L3 — MQTTS topic namespace + ACL + provenance from identity not payload; broker client tests
    status: pending
  - id: l4-ui-domains
    content: L4 — Tenant-aware UI/session; single app domain first; host mapping design only until operator DNS auth
    status: pending
  - id: l5-budgets
    content: L5 — Per-tenant/query budgets + noisy-neighbor lab measurements (report BLOCKED sizes honestly)
    status: pending
  - id: l6-qual-hardening
    content: L6 — Strengthen ZAP/AF + A↔B isolation harness + supply-chain digest scans; fix AF fallback PASS bugs
    status: pending
  - id: l7-migrate-handoff
    content: L7 — Idempotent dry-run migrate → named legacy tenant; export/restore isolation; operator approval checklist
    status: pending
  - id: l8-stress-pin
    content: L8 — Railway CLI tip pin + full stress; fully_qualified; BUG_REPORT 3.5.x; mode still OFF unless operator enables lab
    status: pending
  - id: deferred-stage-c
    content: External IdP / MFA / dedicated-deploy SKUs — after shared-hosting baseline qualified
    status: pending
isProject: false
---

# Wave L — Multi-client shared hosting (3.5.x)

**Depends on:** Wave K **3.4.0 PINNED** ([`wave_k_340_filesystem_pin_master.plan.md`](openfdd_wave_k_340_filesystem_pin_program.plan.md)).  
**Phase-0 ADR** may land as Wave K **K3** (design only). **Product coding** starts only after K7.

**Renamed intent:** Former “shared DB mega” = **shared Railway hub hosting many engineering firms**, not moving the historian into Postgres.

## Goal (from Sep 2026 multi-client assignment — verify on checkout)

- Tenant = engineering firm; building belongs to exactly one tenant; optional per-building auth for building owners.
- MIT / free software — no licensing server or paid point gates. Quotas = capacity protection.
- Preserve **Rust central, React, Parquet historian, DataFusion SQL**. **No** product Python. **No** Postgres time-series. **No** Feather↔RDBMS dual-write for telemetry.
- Shared infrastructure + **tenant-partitioned storage**. A `customer_id` column + UI filter alone is **unacceptable**.
- Feature branch; **multi-tenant mode OFF by default** until qualified. Preserve single-tenant/local.
- Agent creates/tests with **Railway CLI** + existing stress/qualification scripts. No OT writes. No live customer migration / public enable / DNS purchase without explicit operator authorization.

## Law — low-RAM + Railway CLI

Same as Wave K between-build loop. Additionally:

| Tier | When | What |
|------|------|------|
| 1 Per PR | every product PR | unit/integration authz; AppSec; no live OT |
| 2 Candidate digest | every tip Publish set | disposable/synthetic stack; A↔B matrix; ZAP tiers; MQTT ACL tests; restore; bounded perf |
| 3 Field refresh | operator-authorized Railway hub | smoke/freshness/benign permission checks only — **no** active DoS/OT writes on live data |

**Full stress** at each deployable 3.5.x pin the operator treats as ship; **L8** cutover/qualification pin **must** `fully_qualified=true` (no `SKIP_ZAP`). Wave K MEGA gates stay green.

Log every pin/smoke/stress/migrate dry-run in [`BUG_REPORT_OT_MODBUS_HAYSTACK.md`](../BUG_REPORT_OT_MODBUS_HAYSTACK.md).

## Target architecture (lock in K3/L0 ADR)

```text
                    ┌─ transactional control plane (tenants/users/roles/buildings/edges)
Railway shared hub ─┤
                    └─ Parquet historian under server-derived tenant roots
                              ↓
                     DataFusion SessionContext with tenant-scoped providers only
                              ↓
                     /api/* + MCP + jobs (TenantContext fail-closed)
                              ↓
                     MQTTS ACL: tenants/{tid}/buildings/{bid}/edges/{eid}/…
```

| Decision | Default |
|----------|---------|
| Time-series | **Parquet** (partitioned by tenant) + DataFusion |
| Control plane | Small transactional store if session_config/files insufficient — **metadata only** |
| Isolation | Provider/catalog scoping — **not** `WHERE tenant_id` over a shared mega-table |
| MQTT | Identity→topic mapping; reject payload spoofing |
| Rollback | Flag OFF → single-tenant; **3.4.0** images remain pin |
| Dedicated option | Documented for stricter customers |

## Phases → VERSION (one concern per PR)

| Phase | Rev (sketch) | Deliverable | Railway / stress |
|-------|--------------|-------------|------------------|
| **0** | docs (in K3) | ADR, authz matrix, threat model, inventory, ZAP gap list | none |
| **1** | 3.5.0 | Control plane + TenantContext; mode OFF | tip refresh + smoke |
| **2** | 3.5.1 | Tenant Parquet roots + DF providers | smoke; A↔B storage tests |
| **3** | 3.5.2 | MQTTS namespace + ACL + provenance | MQTT client isolation tests |
| **4** | 3.5.3 | UI membership/tenant chrome; domain design | smoke |
| **5** | 3.5.4 | Budgets + noisy-neighbor lab notes | lab measurements |
| **6** | 3.5.5 | ZAP/AF fixes + isolation harness + digest scans | Tier-2 candidate suite |
| **7–8** | 3.5.x pin | Legacy-tenant migrate dry-run + **L8** full stress | Railway CLI full stress |

Exact VERSION numbers may compress if operator prefers fewer pins — **never** skip Tier-2 isolation before claiming multi-tenant ready.

## Phase 0 checklist (K3 / L0 — before product edits)

Reinspect checkout (assignment paths were GitHub-era). Read AGENTS.md trees, SECURITY.md, RAILWAY_* docs, STRESS_CLOSEOUT, qualification README, openapi, appsec/wave-c workflows. `rg` inventory: routes, JWT, SessionContext/TableProvider, storage URLs, import/export, jobs, MQTT, MCP, workers. Deliver ADR + matrix + threat model + dedicated-vs-shared tradeoff + test plan + rollback limits. One agent; no competing builds.

## Security qualification (must harden in L6)

- Fix ZAP/AF **fallback PASS** (AF failure must not become PASS via empty baseline). Separate unauth baseline / auth passive / auth active. Medium exceptions scoped+owned+expiring.
- Seed Tenant A/B with **identical labels, different values**; every resource path positive+negative; prove no cross-tenant mutation.
- Harness self-tests that break scoping and **fail** the gate.
- Scan **actual** image digests; SBOM; no `continue-on-error` on High/Critical.
- `qualification_manifest.json` + SUMMARY.md; `fully_qualified=false` on FAIL/ERROR/SKIPPED/BLOCKED.

## Out of scope (this wave)

- Replacing Parquet historian with Postgres  
- Feather↔DB telemetry dual-write  
- Licensing/billing servers  
- Public multi-tenant enablement / live customer migrate / DNS purchase without operator auth  
- Browser→Mosquitto WebSockets  
- OT command expansion  

## Acceptance (Wave L CLOSED)

- Two synthetic firms cannot read/write/export/subscribe each other’s resources on **any** supported path (evidence in Tier-2 suite)
- Single-tenant mode still default and qualified on 3.4.0 rollback pin
- Multi-tenant mode remains **OFF** in production until operator approval checklist signed
- Stress `fully_qualified=true` on tip; Wave K MEGAs green; isolation+ZAP truthful
- BUG_REPORT **3.5.x** pin line; migrate dry-run counts recorded; Stage C deferred next
