# ADR - Stage C IdP / MFA / SKU (Wave M M4 late-gated)

**Status:** Accepted as late-gated scaffold (not implemented on prod).  
**Date:** 2026-09-12

## Context

Wave L shipped multi-client shared hosting with `multi_tenant=false` on the production hub. Stage C covers identity provider integration, MFA, and commercial SKU boundaries before production multi-tenant ON.

## Decision

1. Keep production `multi_tenant=false` until this ADR's checklist is complete.
2. Lab MT enable uses [`WAVE_M_LAB_MULTI_TENANT_CHECKLIST.md`](../operations/WAVE_M_LAB_MULTI_TENANT_CHECKLIST.md) only.
3. Implement IdP/MFA/SKU as follow-on PRs (PR-I-PR-M) - do not block Track D durable-results work.

## Checklist before prod MT ON

- [ ] IdP contract (OIDC) chosen and secrets rotation documented
- [ ] MFA required for admin/operator roles
- [ ] SKU / entitlement mapping for tenant features
- [ ] Tenant isolation stress on disposable candidate (not MT-OFF smoke alone)
- [ ] Rollback plan that does not auto-restore older telemetry over newer

### Authorized early enable (Wave N — 2026-09-13)

Operator authorized **prod** `OPENFDD_MULTI_TENANT=1` **before** IdP/MFA/SKU complete, with Wave N **ACL + audit + MQTTS continuity stress** as the interim gate. IdP/MFA/SKU remain Soft-OPEN in [`BUG_REPORT_WAVE_N_MULTI_TENANT_SECURITY.md`](../operations/BUG_REPORT_WAVE_N_MULTI_TENANT_SECURITY.md). Agents must still refuse **silent** enable (no waiver recorded). Health `multi_tenant=true` without that waiver + stress evidence remains a release blocker.

## Consequences

Agents must refuse silent prod enable. Health advertising `multi_tenant=true` without checklist evidence **or** an explicit Wave N-style waiver + security stress gate is a release blocker.
