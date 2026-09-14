# BUG REPORT — Wave N Multi-Tenant Security + ACME MQTTS

**Date:** 2026-09-13 (Wave N kickoff) · **updated:** 2026-09-14T00:10Z  
**Platform:** Railway hub (`gleaming-cooperation` / `production`) + ACME on-prem fieldbus OT edge (private; not in GH)  
**Prior ops pin:** `sha-0bfcd81` / **3.5.7** · Wave M durable results · `multi_tenant=false` at kickoff  
**Live hub (this update):** `sha-b2537de` / **3.5.8+b2537deda08e** · **`multi_tenant=true`** · control plane tenants `acme` / `building_100` / `lakeside_sd` · MQTT broker Online after key-perm + SAN repair  
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

## OPEN / Soft-OPEN / CLOSED

| ID | Status | Symptom / work | Next |
|----|--------|----------------|------|
| **wave-n-mt-prod-enable** | CLOSED (ops) | MT ON + users/tenants on volume | Stress still required before OPS PINNED |
| **wave-n-tenant-password-logins** | CLOSED (product #920) | `users.json` + membership mint | Keep secrets in Railway / `.secrets` only |
| **wave-n-mqtt-broker-key-perms** | CLOSED (ops) | `server.key.pem` root `0600` → mosquitto Permission denied / crash-loop | Tip image entrypoint `chmod a+r`/`chown 1883` (rev **3.5.9**); ops recovery via alpine volume helper |
| **wave-n-mqtt-server-san** | CLOSED (ops) | CN-only server cert → rustls/native-tls **hostname mismatch** / `bad certificate` (openssl s_client still OK) | Reissued server cert SAN: `openfdd-mqtt`, `.railway.internal`, `reseau.proxy.rlwy.net`, localhost |
| **wave-n-acme-mqtts-ingest** | Soft-OPEN (ops proven) | Live: `edge:acme:vim-1` CONNECT + health `edges:1` / `ingest_ok≥2` on `sha-b2537de` after key-perm+SAN repair | Re-prove after **3.5.9** re-pin + continuity ≥2×300s; keep Soft-OPEN until OPS PINNED |
| **wave-n-acl-stress** | Soft-OPEN | Product gates 31 present; live trio PASS smoke earlier; full stress pending stream | Run hub stress with MQTTS live |
| **wave-n-mqtts-continuity** | OPEN | Continuity gate 32 needs rising `ingest_ok` across ≥2×300s | After ACME streaming |
| **wave-n-audit-pen-test** | Soft-OPEN | Audit harden shipped in #920 | Assert events in stress |
| **wave-n-zap-mt-af** | Soft-OPEN | Disposable ZAP AF on MT-ON | Artifact when stream healthy |
| **wave-n-fieldbus-fixed-300s** | CLOSED (product #920) | Compile-time 300 s | CI Optional BACnet failed until first-publish (**3.5.9**) |
| **wave-n-optional-bacnet-ci** | OPEN | Tip Actions red: Optional BACnet→MQTT (90s wait < 300s first publish) | Merge first-publish + keep CI tidy green |
| **wave-n-metric-fdd** | Soft-OPEN | Trane VAV metric path | After ingest |
| **wave-n-mstp-vav-addressing** | Soft-OPEN | Identical ZN-T floats may mean wrong MSTP MAC | Fix routing, not invent values |
| **wave-n-csv-tenant-reload** | OPEN | B100 + LAKESIDE_ES under tenant roots after MT partition | Re-import if historian empty |
| **wave-n-lakeside-sd-tenant** | CLOSED (CP) | Tenant + users staged | CSV reload may still be needed |
| **wave-n-pypi-ecm-math-docs** | CLOSED (#920) | GH Pages math + docs | Soft-OPEN wheel refresh if needed |
| **stage-c-idp-mfa-sku** | Soft-OPEN | Early MT waiver; IdP/MFA not done | Track until commercial Stage C |
| **fieldbus-never-cloud** | Doc lock | `openfdd-fieldbus` OT-only | AGENTS + BACNET_OT_POLICY |
| **wave-m-m5-mint-bench** | Soft-OPEN carry | Mint kit/docker/synth59 residual | Do not block Wave N MT |
| **wave-n-gh-tidy** | OPEN | 0 open PRs; tip Actions green; no orphan branches/projects | Required before OPS PINNED |

## Ops learnings (attach to future patch cycles)

1. **Prefer CLI session** (`railway login`); `env -u RAILWAY_TOKEN` if a stale token in `.secrets/.env` shadows auth.  
2. **Mqtt crash-loop blocks volume SFTP / service files** — detach volume → temporary alpine `CMD ["sleep","infinity"]` helper → fix perms/certs → reattach → **delete helper**. Always pass `--project` / link hub before `railway up` (stray projects get scheduled delete).  
3. **Never trust openssl-only as proof of app TLS** — rustls/native-tls need **SAN**; CN-only fails with hostname mismatch / bad certificate.  
4. **Fieldbus poll is fixed 300 s** — CI must not rely on env interval overrides; first MQTT publish must not sleep a full interval (product fix in 3.5.9).  
5. **TCP proxy** `reseau.proxy.rlwy.net:44763` → mqtt `:8883` must stay ACTIVE and listed in server SAN.  
6. **GH tidy gate:** tip required/product checks green; cancel superseded fails; `gh pr list` → 0; delete merged feature branches; no leftover local branches/worktrees.

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
| 2026-09-13 | `sha-b2537de` / 3.5.8 | #920+#921 merged; MT ON; ACL smoke PASS; mqtt crash (key perms) |
| 2026-09-14 | `sha-b2537de` | Key perms fixed via volume helper; server SAN reissued; central MQTTS CONNECT OK (`central:lab` TLSv1.3); ACME PEMs refreshed; ingest proof still OPEN |
| 2026-09-13 | Actions | Optional BACnet→MQTT **FAILURE** on tip (300s lock vs 90s wait) — must clear with 3.5.9 before sign-off |

## Never

- Push ACME private kits, IPs, passwords, point dumps to GitHub  
- Deploy `openfdd-fieldbus` on Railway  
- ActiveScan live Railway OT hub  
- Claim Stage C IdP/MFA complete  
- Greenwash continuity / ACL fails  
- Leave failed tip Actions or stale open PRs/branches after a Wave N merge  
