---
name: openfdd-mt-security
description: >-
  Multi-tenant authz, pre-auth disclosure hardening, and Kali disposition.
  Triggers on: /api/tenants leak, capabilities public, CSP, security.txt,
  IDOR, Tenant A/B, hub admin, agent token, MQTT ACL, ZAP findings, O2c, P2c.
---

# Multi-tenant security (Wave O2c / Wave P2c)

Kali owns **live** ZAP/PEN. Mint implements **product fixes + automated tests**. Never ActiveScan production OT from Mint.

Plans: [`.cursor/plans/wave_o_known_bugs_patch_ce235993.plan.md`](../../../.cursor/plans/wave_o_known_bugs_patch_ce235993.plan.md) § O2c · [`.cursor/plans/wave_p_residual_stress_gh_tidy_ce235993.plan.md`](../../../.cursor/plans/wave_p_residual_stress_gh_tidy_ce235993.plan.md) § P2c.

## Verified Kali findings (2026-09-15) — must stay fixed

| # | Bug | Contract |
|---|-----|----------|
| **V1** | Unauth `GET /api/tenants` used `dev_anonymous()` → **Admin** → full roster | When `OPENFDD_JWT_SECRET` set: **401** without Bearer. Membership filters tenants/buildings. Hub admin (`role=admin` + empty `tenant_ids`) sees all. Never Admin-via-anonymous for listing. |
| **V2** | Unauth `capabilities` / `health/stack` / `building/snapshot` / `dashboard/summary` leaked MCP, protocols, paths, flags | These routes sit on the **JWT-protected** router. Unauth → **401**. Public readiness = `GET /api/health` only (lean). |
| **V3** | CSP / HSTS / `security.txt` | Web nginx: CSP allows Google Fonts (`fonts.googleapis.com` / `fonts.gstatic.com`) + Plotly same-origin/`blob:`; HSTS when `X-Forwarded-Proto=https`; `/.well-known/security.txt` **text/plain** (not SPA HTML). Gate 34. |

## Endpoint → authz (quick matrix)

| Surface | Unauth (auth ON) | Tenant JWT | Hub admin |
|---------|------------------|------------|-----------|
| `/api/health`, `/api/auth/status`, `/api/auth/login` | OK (lean) | OK | OK |
| `/api/tenants`, select, budgets | **401** | own membership only | all |
| capabilities / stack / snapshot / summary | **401** | full | full |
| edges, commands, CSV, FDD, analytics, jobs, export, MQTT kits, agent tools | **401** | **403/404** on foreign ids | cross-tenant OK |
| `/api/admin/*` | **401** | **403** | OK |
| Agent token | n/a | least-privilege, short TTL, tenant-scoped; no admin mint for self | mint via admin path only |

## Tests to run (Mint)

```bash
cargo test -p openfdd-central --test preauth_disclosure
# covers: anonymous_tenants_denied · tenants_scoped_by_membership ·
#         anonymous_topology · health_stays_public_and_lean ·
#         mt_isolation_matrix_select_and_datapath
# + gate 31 ACL · gate 34 headers/security.txt when hub up
```

Foreign building / tenant / job / command IDs must never return **200 + data** (empty soft-leak also FAIL). Deny bodies must include `"ok": false`.

## MQTT (staging / Kali next)

Example ACL comments: [`deploy/mqtt/acl.example`](../../../deploy/mqtt/acl.example). Edge cert for
Tenant A may pub telemetry/status under `openfdd/v1/tenants/{tid}/buildings/{bid}/…`
and sub commands for that edge only — **deny** Tenant B topics and `#` wildcards
across tenants. Production mounts generated `mosquitto.acl` at broker `acl_file`;
rotate/revoke compromised edge creds. Keep central, MCP, mqtt **private** on
Railway; expose **web only**. Broker-side proof = Kali staging pentest (Mint does
not ActiveScan OT).

## Security tooling assurance (3.5.29+)

Brief: `.cursor/agents/openfdd-security-python-harness.md`;
contract: `.cursor/plans/security_stress_integration_audit.md`.
CLI: `scripts/security/openfdd_security_probe.py`. Stress gates **25** / **25b** /
**26** (`OPENFDD_SECURITY_EXECUTE=1` for live; gate **26** uses
`OPENFDD_MQTT_ACL_EXECUTE=1` and candidate runtime broker evidence in the Wave U
field profile). Missing fixtures/tools are BLOCKED, not N/A. The independent
acceptance audit identifies repairs required before the current gate can qualify
that profile: `.cursor/plans/wave_u_independent_acceptance_audit.plan.md`.

- A valid tenant identity and successful own-object control must accompany a
  foreign-object denial. A 401 from failed authentication is not authorization proof.
- Missing credentials/fixtures are BLOCKED; transport/parse failures are ERROR.
  N/A needs applicability evidence. Omitted tests never become PASS.
- Test the evaluator with deliberately broken fixtures, then test real Rust
  middleware/storage separately. Offline manifest tests only verify reporting.
- Keep MQTT continuity in transport; broker identity/topic denial needs its own
  evidence. Scope any PASS to candidate, configuration, fixtures and checked controls.
- Validate the actual `/api/auth/me` `tenant_ids` schema and positive object
  controls. The Wave U acceptance audit and root `MILESTONES.md` govern reopened
  qualification scope; component/source-string checks do not close runtime claims.

## Never

- Fall back to `AuthUser::dev_anonymous()` Admin for tenant/topology list handlers
- Put long-lived JWTs / admin passwords in Cursor config, GHCR images, browser bundles, logs, or the repo
- Claim shared-data launch ready while V1–V3 or pairwise IDOR tests are red
