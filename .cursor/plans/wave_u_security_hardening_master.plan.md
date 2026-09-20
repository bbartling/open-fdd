---
name: Wave U security hardening master
overview: "Security-first Wave U master — Soft-OPEN inventory, supersedes Wave T, many tiny VERSION+GHCR tips, Nessus-pass readiness (no fake scans). Play this; see docs/operations/WAVE_U_MASTER.md."
todos:
  - id: u0-master-md
    content: WAVE_U_MASTER + SUPERSEDE + Soft-OPEN inventory + assurance child + TESTBED retarget
    status: completed
  - id: u1-evaluator-ci
    content: "U1: E01–E08/S01/25b/zap empty-site + CI security/qualification"
    status: pending
  - id: u2-mt-breadth
    content: "U2: expand X/Y IMPLEMENTED MT ACL/JWT matrix"
    status: pending
  - id: u3-deploy-harden
    content: "U3: standalone HTTPS + fieldbus fail-closed + exposure manifests"
    status: pending
  - id: u4-mqtt-acl
    content: "U4: private key modes + generated tenant ACL + observer"
    status: pending
  - id: u5-zap-af
    content: "U5: authenticated ZAP AF on disposable candidate"
    status: pending
  - id: u6-nessus-ready
    content: "U6: Trivy digests + nessus templates/importer + readiness"
    status: pending
  - id: interrupt-hang
    content: Critical interrupt acme-fdd-run-hang
    status: pending
  - id: after-spine-product-fq
    content: "After spine: S5 → PyPI → SQL twins → MEGA FQ"
    status: pending
isProject: false
---

# Wave U — Security-first master (supersedes Wave T)

**Operator start:** [`TESTBED_TAKEOVER.md`](TESTBED_TAKEOVER.md)  
**Cursor play target:** [`.cursor/plans/wave_u_security_hardening_master.plan.md`](../../.cursor/plans/wave_u_security_hardening_master.plan.md)  
**Findings child:** [`.cursor/plans/security_railway_ot_nessus_assurance.plan.md`](../../.cursor/plans/security_railway_ot_nessus_assurance.plan.md)  
**Living Soft-OPEN / tip log:** [`BUG_REPORT_WAVE_P.md`](BUG_REPORT_WAVE_P.md)

**Supersedes:** Wave T Soft-OPEN closeout, Wave T security-master fold-in, and incomplete prior Cursor wave plans (see banners under `.cursor/plans/`). Child detail for product Soft-OPEN after the spine: `wave_s3_*` / `wave_s4_*` / `wave_s5_*`.

## Pins (re-check live)

| Kind | Cite |
|------|------|
| **FQ OPS PINNED** | `3.5.31` / `sha-7b81eb8` · stress `20260919T195100Z` · edge **`vim-1`** |
| **Hub smoke tip** (no FQ claim) | `3.5.33` / `sha-3cd3745` |
| **Wave U** | Security spine first; many tiny VERSION+GHCR tips OK |

## Priority

1. **Security spine** (U0→U6) — leave no rock unturned; tip bumps per FAIL row.  
2. **Critical interrupt only** — `acme-fdd-run-hang` when it blocks hub ops.  
3. **Product Soft-OPEN after spine** — S5 → PyPI → SQL twins → MEGA FQ.  
4. Mid-tips: **smoke only**. Full Railway MEGA FQ after FQ-critical security gates are honest.

## Soft-OPEN inventory (everything)

### Product / hub (after security spine, except hang interrupt)

| ID | Status | Note |
|----|--------|------|
| `acme-fdd-run-hang` | Soft-OPEN | Critical interrupt — ACME `fdd_run_all` stuck `running` |
| `wave-s5-dm-remainder` | Soft-OPEN | DM-04..10 / ECM / Pages / model gate |
| `wave-s3-pypi-mv-oracle` | Soft-OPEN | IPMVP / G14 / Camber→ECM wheel |
| `wave-s4-sql-twins-fq` | Soft-OPEN | SQL M&V twin + Metering + FQ MEGA |

### Security (Wave U owns → tip)

| ID | Tip | Note |
|----|-----|------|
| `sec-harness-evaluator-integrity` | U1 | E01–E08 false-PASS + S01 identity |
| `sec-ci-wire` | U1 | CI runs `tests/security` + `tests/qualification` |
| `sec-harness-mt-breadth` | U2 | X/Y IMPLEMENTED MT ACL/JWT (beat Burp on isolation) |
| `standalone-https-bootstrap` | U3 | No plaintext login path for standalone |
| `fieldbus-mgmt-failclosed` | U3 | Loopback default; no silent open without key |
| `mqtt-key-mode-tenant-acl` | U4 | Private keys not world-readable; generated ACL + observer |
| `zap-af-authenticated` | U5 | Was `kali-zap-af` — AF on disposable candidate |
| `image-digest-trivy` | U6 | Final GHCR digest Critical/High triage |
| `nessus-pass-readiness` | U6 | Hardening + templates/importer — **not** a fake scan |
| `nessus-isolated-assessment` | Soft-OPEN / BLOCKED | Real licensed Nessus on isolated host only |

### Ops / Stage C (remain Soft-OPEN unless authorized)

| ID | Note |
|----|------|
| `stage-c-idp-mfa-sku` | Commercial IdP/MFA |
| `wave-o1-tenant-path-migrate` | Optional `tenants/{tid}/` paths |
| `p2c-mqtt-acl-staging` | Merge into U4 where possible |
| `historian-n-building-scale` | Parquet compaction later |
| `acme-oa-t-dup-reject` | Ops catalog noise |
| `local-bacnet-ot-bench` | FEC/MS/TP shared trunk |
| `edge-kit-soft` | Kit restore ops |

## Nessus — pass readiness vs assessment (no cheat)

| Claim | When allowed |
|-------|----------------|
| **Nessus-pass readiness** | Exposure/TLS/auth/key-mode/image remediations + Trivy digests + port/TLS probes + importer fixtures |
| **Nessus assessment PASS** | Licensed scan on isolated host → validated `.nessus` import → Critical/High=0 |

**Never:** invent `.nessus`, disable TLS checks, blanket waivers, or rename Trivy as Nessus.

## Security spine order

```text
U0 master + SUPERSEDE + inventory
 → U1 E01–E08 + CI
 → U2 MT breadth
 → U3 standalone HTTPS + fieldbus fail-closed
 → U4 MQTT keys + generated ACL
 → U5 authenticated ZAP AF (isolated)
 → U6 Trivy + Nessus readiness templates
 → (interrupt hang anytime)
 → product Soft-OPEN → MEGA FQ
```

## Tip loop (every security tip)

1. Hygiene: 0 open PRs; tip Actions green  
2. BUG_REPORT **FAIL** row before fix  
3. Implement + offline `tests/security` / `tests/qualification`  
4. VERSION patch → PR → squash-merge → GHCR  
5. `check_ghcr_tip_stack.sh` → backup → Railway re-pin and/or isolated candidate  
6. Smoke evidence; Soft-OPEN row update  
7. No mid-spine full FQ unless a dedicated FQ tip is scheduled  

## Anti-patterns

- Playing superseded Wave T / security_master plans  
- PLANNED-as-IMPLEMENTED · FQ from mid-tip · greenwash Soft-OPEN  
- “Nessus certified” without a real report · local stack image builds on bensbench  
- Scanning live OT / Railway provider address space · publishing private scanner artifacts  

## Private findings

Follow [`SECURITY.md`](../../SECURITY.md). Public docs = secure setup + fixed behavior only.
