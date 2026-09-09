---
title: ADR — Multi-client shared hosting
parent: Architecture
nav_order: 12
---

# ADR — Multi-client shared hosting (Wave L Phase 0)

- **Status:** Proposed (Wave K **K3** / Wave L **Phase 0**)
- **Date:** 2026-09-09
- **Program:** Wave L `3.5.x` — shared Railway hub for many engineering firms
- **Depends on:** Wave K **3.4.0 PINNED** before product coding; this ADR may land as design-only K3 meanwhile
- **Related:** [`historian.md`](historian.md), [`datafusion-first.md`](datafusion-first.md), [`SECURITY.md`](../../SECURITY.md), [`docs/operations/RAILWAY_DEPLOYMENT.md`](../operations/RAILWAY_DEPLOYMENT.md), [`docs/operations/STRESS_CLOSEOUT.md`](../operations/STRESS_CLOSEOUT.md), [`scripts/qualification/README.md`](../../scripts/qualification/README.md)

## Context

Open-FDD today is effectively **single-tenant / single hub**: central JWT roles (`viewer` / `operator` / `admin` in `services/central/src/auth.rs`), a shared Parquet historian root (`parquet_root()` / `OPENFDD_STORAGE_URL` / `OPENFDD_PARQUET_ROOT` in `services/central/src/analytics/historian.rs`), building-scoped packages and `session_config.json`, and MQTTS ACL kits under `deploy/mqtt/`. The product UI is React (`frontend/web`); analytics and FDD remain DataFusion SQL on central.

Operators want **one shared Railway hub** that hosts **multiple engineering firms (tenants)** without:

1. Replacing the Parquet historian with Postgres (or any RDBMS) for time-series.
2. Relying on a `customer_id` column plus a **UI filter alone** as isolation.
3. Breaking the default single-tenant / local Docker path.

Wave L renames the older “shared DB mega” intent: **shared hosting**, not a shared mega-table historian. Product code is gated on Wave K filesystem/historian pin; this ADR locks architecture before L1+.

## Decision

1. **Historian stays Parquet + DataFusion.** Time-series remains immutable Parquet under storage roots resolved by central (`OPENFDD_STORAGE_URL` preferred; `OPENFDD_PARQUET_ROOT` legacy). Feather remains non-canonical cache/interop only ([`historian.md`](historian.md)). **Do not** introduce Postgres (or similar) as the telemetry store; **do not** dual-write Feather↔RDBMS for historian rows.

2. **Shared Railway hub + tenant-partitioned Parquet.** When multi-tenant mode is enabled, each tenant gets a **server-derived storage root** (or equivalent Hive prefix) so DataFusion registers **tenant-scoped providers/catalogs only**. Isolation is fail-closed provider scoping — **not** `WHERE tenant_id` over one shared registered mega-table.

3. **Optional transactional control plane (metadata only).** Tenants, users, memberships, buildings, and edge identity bindings may live in a small transactional store if file/`session_config` layouts prove insufficient. That store **must not** hold historian time-series. Building ∈ exactly one tenant.

4. **Feature flag OFF by default.** Multi-tenant mode ships **disabled**. Single-tenant behavior (today’s hub semantics) remains the default for local, CI, and production until an operator checklist enables shared mode after Tier-2 evidence.

5. **Authz is identity + TenantContext, not UI chrome.** JWT claims (`JwtClaims` in `services/central/src/auth.rs`) and route middleware (`services/central/src/routes.rs`) gain tenant membership / building scope server-side. SPA filters are convenience only. MCP, jobs, import/export, and MQTT paths honor the same fail-closed `TenantContext`.

6. **MQTTS namespace + ACL from identity.** Target topic shape: `tenants/{tid}/buildings/{bid}/edges/{eid}/…`. Broker ACL (`deploy/mqtt/certs/acl`, kit ACLs under `deploy/mqtt/kits/`) and central ingest must derive tenant/building from **authenticated identity**, not client-supplied payload labels.

7. **Dedicated deploys remain a first-class alternative** for customers who refuse shared tenancy (see tradeoff below). Shared mode never becomes the only supported topology.

## Architecture sketch

```text
                    ┌─ control plane (tenants/users/roles/buildings/edges)  [metadata]
Railway shared hub ─┤
                    └─ Parquet under server-derived tenant roots
                              ↓
                     DataFusion SessionContext + tenant-scoped providers only
                              ↓
                     /api/* + MCP + jobs (TenantContext fail-closed)
                              ↓
                     MQTTS: tenants/{tid}/buildings/{bid}/edges/{eid}/…
```

## Authz matrix sketch

| Actor | Role (JWT) | Tenant membership | Buildings | Historian / FDD read | Mutating /api (import, activate, jobs) | MQTTS publish | MQTTS subscribe |
|-------|------------|-------------------|-----------|----------------------|----------------------------------------|---------------|-----------------|
| Hub operator | `admin` | all (or hub-wide) | all | yes | yes | ACL-bound | ACL-bound |
| Firm engineer | `operator` | own tenant(s) | tenant buildings | scoped | scoped | edges in membership | same |
| Building owner (optional) | `viewer` or scoped `operator` | one tenant | subset | scoped read | deny by default | deny | optional telemetry |
| Agent / MCP | `operator` via agent token | explicit membership | scoped | scoped | scoped + confirm gates | N/A (API) | N/A |
| Unauthenticated | — | none | none | deny off-loopback | deny | deny | deny |

**Rules of thumb**

- Missing or ambiguous tenant → **deny** (fail closed), never “all buildings.”
- Role elevation does not bypass tenant partition unless the subject is a documented hub `admin` with hub-wide scope.
- Deployment-wide passwords (`OPENFDD_VIEWER_PASSWORD`, etc.) remain **not** tenant isolation; they are single-hub conveniences until membership claims exist.
- UI `customer_id` / building pickers without server TenantContext checks are **out of policy**.

## Threat model sketch

| Threat | Example | Mitigations |
|--------|---------|-------------|
| Cross-tenant read | Tenant A JWT lists Tenant B buildings / Parquet | Tenant-scoped DF providers; deny on path/id mismatch; A↔B harness |
| Cross-tenant write | Import/package append into foreign building | Membership check before workspace/`parquet_root` resolve; job workspace isolation |
| Payload spoofing | MQTT edge publishes `building_id=B` while cert is for A | Identity→topic ACL; reject label≠identity |
| Confused deputy | Hub admin token leaked into MCP | Short-lived agent tokens (`POST /api/auth/agent-token`); least privilege memberships |
| Cache/job bleed | Shared temp or session registers both tenants | Per-request SessionContext; no global cross-tenant register |
| Noisy neighbor | One tenant’s FDD flood starves hub | Per-tenant query/job budgets (Wave L Phase 5); dedicated SKU escape hatch |
| Backup restore mix-up | Restore Tenant A artifact into B root | Tenant-labeled backup paths; dry-run migrate + restore isolation tests |
| Flag foot-gun | Shared mode on without Tier-2 | Default OFF; operator checklist; `fully_qualified` gate |

**Out of scope for this wave:** browser→Mosquitto WebSocket, OT command expansion, public multi-tenant enable without operator auth, live customer DNS purchase.

## Dedicated vs shared tradeoff

| | **Shared hub (Wave L target)** | **Dedicated deploy** |
|--|-------------------------------|----------------------|
| Cost / ops | One Railway project; shared central/mqtt/web | Per-customer stack; higher ops |
| Isolation | Soft + hard: TenantContext, Parquet roots, MQTT ACL | Process/volume boundary; simpler mental model |
| Blast radius | Mis-scoping affects many firms | Confined to one customer |
| Fit | MIT/free multi-firm bench & early multi-client | Regulated / distrustful / high-quota tenants |
| Rollback | Flag OFF → single-tenant semantics on same images | Redeploy prior pin; no shared-mode surface |

**Decision:** Implement shared hosting with strong partitions; **document dedicated** as the supported escape hatch. Do not force shared mode as the only production path.

## Migration to a legacy tenant

Existing single-hub data (buildings, Parquet tree, `session_config`, MQTT kits) maps into one named **legacy tenant** (e.g. `legacy` / operator-chosen id).

1. **Inventory** current buildings, storage URL, jobs, MQTT edge kits — no live cutover in Phase 0.
2. **Dry-run migrate (L7):** idempotent script/checklist that assigns all existing buildings to the legacy tenant, rewrites roots/prefixes **without** deleting Parquet, and verifies read paths under TenantContext with mode still OFF or lab-only.
3. **Preserve pin:** Wave K **3.4.0** images remain the rollback pin; migration must be reversible by flag OFF + prior digest.
4. **No silent live migrate:** operator authorization required before touching production Railway volumes or customer DNS.

## Test plan tiers

| Tier | When | Scope |
|------|------|--------|
| **1 — Per PR** | every product PR | Authz unit/integration; TenantContext deny paths; AppSec; no live OT |
| **2 — Candidate digest** | every tip Publish set treated as multi-tenant candidate | Synthetic Tenant A/B (identical labels, different values); storage + API + MQTT ACL matrix; ZAP unauth / auth passive / auth active; restore isolation; bounded perf; harness self-tests that **fail** when scoping is broken |
| **3 — Field refresh** | operator-authorized Railway hub | Smoke, freshness, benign permission checks only — **no** DoS / OT writes on live data |

Never claim multi-tenant ready without **Tier-2** isolation evidence. L8 cutover pin requires `fully_qualified=true` (no `SKIP_ZAP`). Log pins/smoke/stress/migrate dry-runs in [`docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md`](../operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md).

## Rollback

1. Keep multi-tenant **feature flag OFF** → restore today’s single-tenant request path.
2. Retain ability to **re-pin GHCR digests** to Wave K **3.4.0** (central → mqtt → web per Railway ops notes).
3. Do not delete Parquet during failed shared-mode experiments; tenant roots are additive prefixes where possible.
4. Control-plane schema (if introduced) must degrade gracefully when mode is OFF (unused or ignored).

## Railway CLI testing notes

- Use `@railway/cli` against the linked hub project; service names and re-pin order follow [`docs/operations/RAILWAY_DEPLOYMENT.md`](../operations/RAILWAY_DEPLOYMENT.md) / agent Railway skill — typically central → mqtt → web, then fieldbus up scripts when needed.
- Prefer **tip GHCR `sha-*` pulls** on the hub; do not local-`docker build` central/web/mqtt/fieldbus on the low-RAM bench during qualification.
- Between builds: tip Publish → tip gate → backup (`scripts/railway_central_workspace_backup.sh` when used) → re-pin → soak → smoke → BUG_REPORT.
- Tier-3 on the live hub is **smoke/freshness only**; A↔B aggression and ZAP active belong on disposable/synthetic stacks (Tier-2).
- Never commit `RAILWAY_TOKEN` or JWT dumps; never treat Railway AI as the FDD agent.
- MQTT ACL path on tip stacks: `acl_file` under `deploy/mqtt/certs/acl` (not only a non-mounted `deploy/mqtt/acl`).

## Consequences

- Wave L product PRs (L1+) implement TenantContext, partitioned Parquet providers, MQTT namespace, UI membership chrome, budgets, and qualification harnesses **after** 3.4.0 is pinned.
- Postgres/RDBMS may appear **only** as an optional control-plane dependency — never as historian SoT.
- Single-tenant users see no behavior change while the flag remains OFF.
- Security bar rises: isolation harness + ZAP/AF correctness become release gates for shared mode.

## Non-goals (this ADR / Wave L)

- Postgres (or other RDBMS) time-series historian
- Feather↔DB telemetry dual-write
- Licensing / paid point gates
- Public multi-tenant enable without operator authorization
- External IdP / MFA / dedicated SKU automation (Stage C — after shared baseline qualifies)

## Alternatives considered

| Alternative | Why rejected (for Wave L) |
|-------------|---------------------------|
| Postgres historian + SQL over RDBMS | Violates Parquet/DataFusion contract; heavy migration; dual-write risk |
| Shared Parquet table + `WHERE tenant_id` | Easy to miss a path; unacceptable isolation story vs provider scoping |
| UI-only `customer_id` filter | Trivially bypassed via API/MCP/jobs/MQTT |
| Multi-tenant ON by default | Unsafe until Tier-2; breaks single-tenant expectation |
| Shared-only (no dedicated option) | Some customers need process-level isolation; keep dedicated documented |

## Acceptance (when Wave L may close — foreshadow)

- Two synthetic firms isolated on every supported path (Tier-2 evidence).
- Single-tenant default still works; **3.4.0** rollback pin retained.
- Multi-tenant **OFF** in prod until operator checklist signed.
- Stress green; BUG_REPORT records **3.5.x**; Stage C remains deferred.
