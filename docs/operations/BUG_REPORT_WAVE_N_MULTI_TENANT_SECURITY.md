# BUG REPORT — Wave N Multi-Tenant Security + ACME MQTTS

**Date:** 2026-09-13 (Wave N kickoff) · **updated:** 2026-09-14T02:51Z  
**Platform:** Railway hub (`gleaming-cooperation` / `production`) + ACME on-prem fieldbus OT edge (private; not in GH)  
**OPS PINNED:** `sha-9072e0b` / **3.5.10+9072e0b9fcf6** · `multi_tenant=true` · ACME streaming · ACL trio+mapping/series PASS (`reports/wave_n_tip_pin_3510_20260914T052952Z`) · continuity pending/see evidence  
**Rollback:** `sha-1f94cdf` / **3.5.9** or `sha-0bfcd81` / **3.5.7** (Wave M)  
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
| **wave-n-mt-prod-enable** | CLOSED | MT ON + users/tenants on volume | — |
| **wave-n-tenant-password-logins** | CLOSED (#920) | `users.json` + membership mint | Secrets Railway / `.secrets` only |
| **wave-n-mqtt-broker-key-perms** | CLOSED (ops+3.5.9) | root `0600` key → mosquitto crash-loop | Entrypoint chmod/chown; alpine volume helper documented |
| **wave-n-mqtt-server-san** | CLOSED (ops) | CN-only cert → rustls hostname mismatch | Server SAN includes proxy host |
| **wave-n-acme-mqtts-ingest** | CLOSED (ops pin) | ACME → Railway ingest | Keep ACME private refresh on tip `sha-*` |
| **wave-n-acl-stress** | CLOSED (live 3.5.10) | Gate 31 list+select+mapping+series PASS on `sha-9072e0b` | Re-run each patch cycle |
| **wave-n-mqtts-continuity** | CLOSED (live 3.5.10) | Gate 32 PASS `ingest_ok` 0→2 @320s after ACME refresh | Prefer ≥2×300s for heavy pins |
| **wave-n-audit-pen-test** | Soft-OPEN | Audit harden shipped | Assert event rows in next full hub stress |
| **wave-n-zap-mt-af** | Soft-OPEN | Disposable ZAP AF on MT-ON | Schedule when convenient |
| **wave-n-fieldbus-fixed-300s** | CLOSED (#920/#922) | Compile-time 300 s + first publish immediate | — |
| **wave-n-optional-bacnet-ci** | CLOSED (#922) | Tip Optional BACnet **success** on `1f94cdf` | Keep 360s smoke wait for base-image PR runs |
| **wave-n-metric-fdd** | Soft-OPEN | Trane VAV metric path | Follow-up soak |
| **wave-n-mstp-vav-addressing** | Soft-OPEN | Identical ZN-T floats may mean wrong MSTP MAC | Fix routing, not invent values |
| **wave-n-csv-tenant-reload** | Soft-OPEN | Hub-root `building=BUILDING_100` / `LAKESIDE_ES` still readable by owned JWTs after data-path ACL; no `tenants/{tid}/` tree yet | Optional migrate / re-import under tenant roots |
| **wave-n-lakeside-sd-tenant** | CLOSED (CP) | Tenant + users live | — |
| **wave-n-pypi-ecm-math-docs** | CLOSED (#920) | GH Pages math + docs | Soft-OPEN wheel refresh if needed |
| **stage-c-idp-mfa-sku** | Soft-OPEN | Early MT waiver; IdP/MFA not done | Commercial Stage C |
| **fieldbus-never-cloud** | Doc lock | `openfdd-fieldbus` OT-only | — |
| **wave-m-m5-mint-bench** | Soft-OPEN carry | Mint kit/docker/synth59 residual | Do not block Wave N |
| **wave-n-gh-tidy** | CLOSED | 0 open PRs; tip Actions green on `1f94cdf`; feature branch deleted | Keep each merge tidy |

## Ops learnings (attach to future patch cycles)

1. **Prefer CLI session** (`railway login`); `env -u RAILWAY_TOKEN` if a stale token in `.secrets/.env` shadows auth.  
2. **Mqtt crash-loop blocks volume SFTP / service files** — detach volume → temporary alpine `CMD ["sleep","infinity"]` helper → fix perms/certs → reattach → **delete helper**. Always pass `--project` / link hub before `railway up` (stray projects get scheduled delete).  
3. **Never trust openssl-only as proof of app TLS** — rustls/native-tls need **SAN**; CN-only fails with hostname mismatch / bad certificate.  
4. **Fieldbus poll is fixed 300 s** — CI must not rely on env interval overrides; first MQTT publish must not sleep a full interval (product fix in 3.5.9). Optional BACnet PR jobs test **base** GHCR images — keep smoke wait ≥300s.  
5. **TCP proxy** `reseau.proxy.rlwy.net:44763` → mqtt `:8883` must stay ACTIVE and listed in server SAN.  
6. **GH tidy gate:** tip required/product checks green; cancel superseded fails; `gh pr list` → 0; delete merged feature branches; no leftover local branches/worktrees.  
7. **First MQTT publish races empty poll** on tip — expect `edges≥1` immediately; `ingest_ok` may wait one 300s cycle unless `poll/once` then restart.  
8. **List/select ACL ≠ data-path ACL** — gate 31 must also probe `/api/csv/import/package/mapping` + `/api/fdd/series` for foreign `building_id` → **403**. `TenantContext::allow_building` must wrap FDD/analytics/CSV reads (3.5.10+).  

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
| 2026-09-14 | `sha-b2537de` | Key perms + server SAN fixed; central CONNECT; ACME ingest_ok climbing |
| 2026-09-14 | Actions | #922 tip: Optional BACnet **PASS**; all tip workflows success |
| 2026-09-14 | **OPS PINNED** `sha-1f94cdf` / 3.5.9 | Hub+ACME re-pin; ACL list/select PASS; continuity `ingest_ok` 1→2; backup `20260914T023409Z` |
| 2026-09-14 | tip `sha-1f94cdf` | Honest FAIL: mapping/series still returned foreign buildings (hub-root Parquet) |
| 2026-09-14 | **OPS PINNED** `sha-9072e0b` / 3.5.10 | #923 data-path ACL; gate 31 mapping+series PASS; continuity 0→2; backup `20260914T052821Z`; ACME fieldbus `sha-1f94cdf` (hub `sha-9072e0b`) |

## Never

- Push ACME private kits, IPs, passwords, point dumps to GitHub  
- Deploy `openfdd-fieldbus` on Railway  
- ActiveScan live Railway OT hub  
- Claim Stage C IdP/MFA complete  
- Greenwash continuity / ACL fails  
- Leave failed tip Actions or stale open PRs/branches after a Wave N merge  
