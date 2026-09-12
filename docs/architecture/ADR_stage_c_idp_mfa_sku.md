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

## Consequences

Agents must refuse silent prod enable. Health advertising `multi_tenant=true` without checklist evidence is a release blocker.
