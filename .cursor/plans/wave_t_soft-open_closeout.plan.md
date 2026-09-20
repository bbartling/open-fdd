---
name: Wave T Soft-OPEN closeout
overview: "Close Wave S Soft-OPEN from BUG_REPORT: acme-fdd-run-hang, S5 remainder, PyPI M&V, MT-security harness breadth (Burp-class authz matrix), then S4 SQL/UI + one MEGA FQ. Mid-tips smoke; GH tidy every tip."
todos:
  - id: h0-hygiene
    content: "Hygiene START: 0 open PRs; tip Actions green; hub ACME MQTTS live; confirm hang repro"
    status: pending
  - id: t0-fdd-hang
    content: "T0: diagnose+fix acme-fdd-run-hang → 3.5.34 → GHCR → smoke (ACME FDD completes)"
    status: pending
  - id: t1-s5-remainder
    content: "T1: S5 DM-04+ / model gate / EQ slice → 3.5.35 → GHCR smoke; evidence matrix"
    status: pending
  - id: t-sec-harness
    content: "T_sec: expand X/Y IMPLEMENTED MT ACL/JWT matrix (beat manual Burp on isolation) → tip+CI"
    status: pending
  - id: t2-s3-pypi
    content: "T2: PyPI M&V/change-point oracle + cookbook/wheel → smoke"
    status: pending
  - id: t3-s4-fq
    content: "T3: SQL twins + Metering UI → GHCR → fieldbus → MEGA FQ EXECUTE=1"
    status: pending
  - id: closeout
    content: BUG_REPORT OPS PINNED + agent_spec pins + Soft-OPEN rows CLOSED; GH hygiene END
    status: pending
isProject: false
---

# Wave T — Soft-OPEN closeout + MEGA FQ

**Operator start:** [`docs/operations/TESTBED_TAKEOVER.md`](../../docs/operations/TESTBED_TAKEOVER.md)

**Supersedes** cancelled Wave S todos S3/S4 and Soft-OPEN S5 remainder in [`wave_s_master_ecb88a61.plan.md`](wave_s_master_ecb88a61.plan.md).

**Baseline:** FQ OPS PINNED `3.5.31` / `sha-7b81eb8` · hub smoke tip `3.5.33` / `sha-3cd3745` · tracker [`docs/operations/BUG_REPORT_WAVE_P.md`](../../docs/operations/BUG_REPORT_WAVE_P.md) · evidence [`wave_s_data_model_evidence.md`](wave_s_data_model_evidence.md).

**Owns (product Soft-OPEN → tip):** `acme-fdd-run-hang` · `wave-s5-dm-remainder` · `wave-s3-pypi-mv-oracle` · `wave-s4-sql-twins-fq` · **`sec-harness-mt-breadth`** (new).

**Stays Soft-OPEN (do not tip):** `stage-c-idp-mfa-sku` · `kali-zap-af` · `p2c-mqtt-acl-staging` · `local-bacnet-ot-bench` · `wave-o1-tenant-path-migrate` · `historian-n-building-scale` · `acme-oa-t-dup-reject` (ops catalog noise).

```mermaid
flowchart LR
  H0[H0_hygiene]
  T0[T0_fdd_hang]
  T1[T1_S5_remainder]
  Tsec[T_sec_MT_harness]
  T2[T2_S3_pypi]
  T3[T3_S4_FQ]
  H0 --> T0
  T0 -->|GHCR_smoke| T1
  T1 -->|GHCR_smoke| Tsec
  Tsec -->|GHCR_smoke| T2
  T2 -->|GHCR_smoke| T3
  T3 -->|GHCR_plus_FQ_MEGA| Done[Wave_T_OPS_PINNED]
```

## Stress / GH policy

| When | What |
|------|------|
| **Every tip** | Hygiene START → PR squash-merge `--delete-branch` → Publish → `check_ghcr_tip_stack.sh` → backup → Railway re-pin → fieldbus → ACME ingest (`EXPECTED_EDGE_ID=vim-1`) |
| **T0 / T1 / T_sec / T2** | Smoke only (ACME FDD completes after T0; gate 25 dry-run OK) |
| **T3 only** | Full `run_railway_hub_stress.sh` + `OPENFDD_SECURITY_EXECUTE=1` → `fully_qualified=true` (19+35+25/25b; 26 N/A OK) |
| **Never** | Mid-wave FQ; local stack image builds; older-pin stress cites; greenwash Soft-OPEN |

Child plans: [`wave_s3_pypi_mv_camber_oracle.plan.md`](wave_s3_pypi_mv_camber_oracle.plan.md) · [`wave_s5_data_model_graph_ecm.plan.md`](wave_s5_data_model_graph_ecm.plan.md) · [`wave_s4_sql_oracle_twins_fq.plan.md`](wave_s4_sql_oracle_twins_fq.plan.md).

---

### H0 — Hygiene START

- `gh pr list` empty; prune gone remotes; hub healthy
- Confirm ACME MQTTS (`vim-1`); note Soft-OPEN hang before T0

### T0 — Patch `acme-fdd-run-hang` (VERSION **3.5.34**)

1. Reproduce ACME `fdd_run_all` stuck `running`; clear via `DELETE /api/actions`
2. Log FAIL in BUG_REPORT before fix
3. Minimal product fix + regression
4. GHCR → smoke: ACME FDD terminal + `rules_failed=0`
5. Soft-OPEN row → CLOSED

### T1 — S5 remainder (VERSION **3.5.35**, smoke)

Bounded: DM-04/05 · model/ECM gate wire · EQ slice · Pages for shipped · Soft-OPEN unmeasured SPARQL/PERF · evidence matrix · GHCR smoke.

### T_sec — Security harness MT breadth (VERSION tip or fold into T0/T1)

**BUG_REPORT id:** `sec-harness-mt-breadth`

**Goal:** Python suites X/Y **outperform a human Burp session on JWT + multi-tenant isolation** (more routes, A/B canaries, detectors, CI+FQ). Do **not** claim XSS/SQLi/AF parity — that remains ZAP baseline + Soft-OPEN `kali-zap-af`.

1. Grow `IMPLEMENTED` inventory (today ~16/138) with suite-emitted checks for high-value authenticated GETs + foreign deny (datasets, mapping, session-config, analytics, data-model export) — unique check IDs only
2. Offline unittest + inventory integrity PASS; never mark PLANNED as tested
3. Refresh [`SECURITY_HARNESS_EVIDENCE_3.5.30.md`](../../docs/operations/SECURITY_HARNESS_EVIDENCE_3.5.30.md) (or tip-named successor)
4. GHCR if product VERSION bumped; smoke gate 25 dry-run; FQ evidence on T3

May ship in the same tip as T0 or T1 if the diff stays focused; otherwise its own patch VERSION.

### T2 — S3 PyPI M&V oracle

Per S3 child: IPMVP/G14 · cookbook · wheel · smoke · Soft-OPEN unfinished Camber families.

### T3 — S4 SQL twins + Metering + MEGA FQ (final VERSION)

Per S4 child + T1 model gate in stress · `OPENFDD_SECURITY_EXECUTE=1` · `fully_qualified=true` · OPS PINNED closeout.

---

## Security vs Burp / ZAP (contract)

| Layer | Owner | Wave T bar |
|-------|-------|------------|
| MT ACL / JWT / role matrix | `scripts/security/` X/Y → gates 25/25b | **Must beat** manual Burp for coverage + repeatability |
| Deploy headers / security.txt / CORS | Suite Z | Keep; expand only with inventory honesty |
| Passive URL scan | ZAP in hub stress | High=0; Medium dispositions JSON |
| Authenticated active scan | Soft-OPEN Kali / Burp AF | Not claimed PASS until Soft-OPEN closes |

## Hygiene END

0 open PRs; no `tip/`/`docs/` remotes; tip Actions green; Soft-OPEN rows honest in BUG_REPORT.

## Anti-patterns

- FQ after mid-tips · empty SPARQL PASS · “100% secure” / “Burp obsolete” · PLANNED-as-IMPLEMENTED · local stack builds
