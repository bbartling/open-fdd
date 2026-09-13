# BUG REPORT — Wave N Multi-Tenant Security + ACME MQTTS

**Date:** 2026-09-13 (Wave N kickoff)  
**Platform:** Railway hub (`gleaming-cooperation` / `production`) + ACME on-prem fieldbus OT edge (private; not in GH)  
**Prior ops pin:** `sha-0bfcd81` / **3.5.7** · Wave M durable results · `multi_tenant=false` at kickoff  
**Program:** Wave N — prod MT ON (authorized Stage C early waiver) · three client tenants · ACME MQTTS bench · ACL/audit/continuity stress · fixed 300 s fieldbus · PyPI/ECM GH Pages math  
**Cursor plan:** [`wave_n_acme_mt_security_7f2a9c01`](../../../.cursor/plans/wave_n_acme_mt_security_7f2a9c01.plan.md)  
**OT BUG_REPORT pointer:** [`BUG_REPORT_OT_MODBUS_HAYSTACK.md`](BUG_REPORT_OT_MODBUS_HAYSTACK.md) (hardware/MQTT Soft-OPEN carry; MT security lives **here**)  
**Stage C:** IdP/MFA/SKU remain **Soft-OPEN**; operator authorized early `OPENFDD_MULTI_TENANT=1` on 2026-09-13 with **security stress as the gate** (see waiver below).

## Tenants (control plane)

| Tenant id | Buildings | Kind |
|-----------|-----------|------|
| `acme` | `ACME` | Live BACnet → MQTTS OT bench |
| `building_100` | `BUILDING_100` | CSV demo client (reload after MT) |
| `lakeside_sd` | `LAKESIDE_ES` | Creekside / Lakeside school district |
| (parked) | `BUILDING_50`, `bldg2`, synth59 | Soft-OPEN — do not attach to the three JWTs |

Hub `admin`: empty `tenant_ids`, **no buildings owned**, can select any client.

## OPEN / Soft-OPEN

| ID | Status | Symptom / work | Next |
|----|--------|----------------|------|
| **wave-n-mt-prod-enable** | OPEN | Flip Railway MT ON after backup + control plane + users | Backup → tenants.json → MT=1 → health true |
| **wave-n-tenant-password-logins** | OPEN | Env passwords mint empty `tenant_ids` | `users.json` + mint with membership |
| **wave-n-acme-mqtts-ingest** | OPEN | ACME edge → Railway ingest / edges proof | Tenant topics + ACL + fieldbus refresh |
| **wave-n-acl-stress** | OPEN | Pairwise ACME ↔ B100 ↔ lakeside_sd deny | Hub stress gates |
| **wave-n-mqtts-continuity** | OPEN | No ingest stall across poll cycles | Continuity soak gate |
| **wave-n-audit-pen-test** | OPEN | Audit gaps for tenant deny / select / ingest reject | Harden + stress assert |
| **wave-n-zap-mt-af** | Soft-OPEN | Disposable ZAP AF still documented MT=0 | MT-ON disposable AF artifact |
| **wave-n-fieldbus-fixed-300s** | OPEN | Adjustable poll can burst MQTTS | Compile-time 300 s |
| **wave-n-metric-fdd** | OPEN | Trane VAV metric BACnet → FDD | unit_system soak |
| **wave-n-mstp-vav-addressing** | Soft-OPEN | Identical ZN-T floats may mean wrong MSTP MAC | Fix routing, not invent values |
| **wave-n-csv-tenant-reload** | OPEN | B100 + LAKESIDE_ES under correct tenant roots | Re-import packages |
| **wave-n-lakeside-sd-tenant** | OPEN | School district must not share ACME/B100 | Control plane + users |
| **wave-n-pypi-ecm-math-docs** | OPEN | GH Pages math + PyPI refresh for agents | MathJax + wheel + skills |
| **stage-c-idp-mfa-sku** | Soft-OPEN | Early MT waiver; IdP/MFA not done | Track until commercial Stage C |
| **fieldbus-never-cloud** | Doc lock | `openfdd-fieldbus` OT-only | AGENTS + BACNET_OT_POLICY |
| **wave-m-m5-mint-bench** | Soft-OPEN carry | Mint kit/docker/synth59 residual | Do not block Wave N MT |

## Stage C early-MT waiver (2026-09-13)

| Field | Value |
|-------|--------|
| Operator | Ben Bartling (user authorization in Cursor session) |
| Decision | Enable `OPENFDD_MULTI_TENANT=1` on Railway production **before** IdP/MFA/SKU checklist complete |
| Gate | Wave N ACL + audit + MQTTS continuity stress must PASS (or honest FAIL logged here) before claiming ops pin |
| Still Soft-OPEN | IdP (OIDC), MFA for admin/operator, SKU entitlements — [`ADR_stage_c_idp_mfa_sku.md`](../architecture/ADR_stage_c_idp_mfa_sku.md) |
| Rollback | `OPENFDD_MULTI_TENANT=0` + prior pin `sha-0bfcd81` / 3.5.7; do not delete Parquet |

## Evidence log

| UTC | Tip / health | Note |
|-----|--------------|------|
| 2026-09-13 | kickoff `sha-0bfcd81` / 3.5.7 | Plan approved; MT still OFF on live hub |

| 2026-09-13 | agent network | Cursor agent shell still cannot reach gh/railway/crates.io (sandbox proxy). Host auth must be proven via `scripts/ops/wave_n_auth_validate_host.sh` → `reports/wave_n_auth_host_status.json`. `hosts.yml` still missing `oauth_token` from agent view. |

## Never

- Push ACME private kits, IPs, passwords, point dumps to GitHub  
- Deploy `openfdd-fieldbus` on Railway  
- ActiveScan live Railway OT hub  
- Claim Stage C IdP/MFA complete  
- Greenwash continuity / ACL fails  
