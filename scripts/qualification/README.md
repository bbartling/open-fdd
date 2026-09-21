# Qualification harness (entry point)

**Profiles**

| Profile | Entry | Environment |
|---------|-------|-------------|
| `railway_field` | `./scripts/nightly-ot-bench/run_railway_hub_stress.sh` | Authorized live ops window; includes data mutations and telemetry pause/resume, plus public ZAP baseline |
| `lab_local` | `./scripts/nightly-ot-bench/run_all.sh` | Disposable/local stack (not field closeout) |
| `harness_selftest` | `python3 scripts/qualification/write_manifest.py selftest` | No network |

**Tier split** (see `docs/operations/STRESS_CLOSEOUT.md`):

1. **Per PR** — unit/contract, AppSec workflows, synthetic harness gates.
2. **Per published candidate (isolated)** — digest-pinned disposable stack; authenticated ZAP AF planned here (not live OT).
3. **Railway field** — this wrapper: CSV fault matrix + expected-edge telemetry + public baseline ZAP + auth role matrix + Railway MCP parity.

## Truthful verdicts

- Manifest schema: `openfdd_qualification_manifest_v1` (`write_manifest.py`).
- Statuses: `PASS` | `FAIL` | `ERROR` | `SKIPPED` | `BLOCKED` | `NOT_APPLICABLE`.
- Required gate `SKIPPED` / `BLOCKED` / `ERROR` ⇒ `fully_qualified=false` (e.g. `SKIP_ZAP=1`).
- `SUMMARY.md` is **generated** from the manifest — never a static success sentence.

### Security assurance scope

Manifest v1 summarizes recorded verdicts for the caller's required-gate list.
It does not establish route coverage or validate HTTP assertions/artifact freshness.
Its `fully_qualified` field is not a blanket security certification.
An empty required list or an entirely `NOT_APPLICABLE` run is BLOCKED; a required
N/A gate needs a nonblank reason. Reasons alone do not prove feature applicability.

The security dimension includes recorded role/tenant/ACL/header gates **and**
Python harness gates `25_security_python_harness` / `25b_security_post_stress` /
`26_security_mqtt_acl` when required by the runner. MQTT continuity (21) and
telemetry pause/resume (35) are transport evidence, not broker authorization
tests. All-N/A security remains `NOT_APPLICABLE`; no security evidence remains
`null`. Dry-run harness artifacts cannot fully qualify.

**Wave S4 M&V twin (Soft-OPEN):** `scripts/qualification/mv_sql_oracle_twin_gate.py`
+ gate `36_mv_sql_oracle_twin.sh`. Default **BLOCKED** without
`OPENFDD_SECURITY_EXECUTE=1` (or `OPENFDD_MV_TWIN_EXECUTE=1`). With EXECUTE,
compares thin PyPI twin vs `POST /api/analytics/mv` on
`fixtures/mv_change_point_seed.json`. Not OPS PINNED until FQ MEGA.

Harness: [`scripts/security/README.md`](../security/README.md). Offline tests:
`python3 -B -m unittest discover -s tests/security -v`. Audit contract:
[`.cursor/plans/security_stress_integration_audit.md`](../../.cursor/plans/security_stress_integration_audit.md).
Live execute / Railway ACL windows remain HOLD until authorized; dry-run is the default.

Offline reporting regression tests (no application/network testing):

```bash
python3 -B -m unittest discover -s tests/qualification -v
python3 -B scripts/qualification/write_manifest.py selftest
```

## Scripts

| Script | Role |
|--------|------|
| `write_manifest.py` | Create / record / finalize / selftest |
| `zap_baseline_verdict.py` | Parse ZAP JSON; High always fails; Medium explicit |
| `auth_role_matrix.sh` | anon/admin/operator(/viewer) REST checks |
| `railway_mcp_accuracy.sh` | MCP↔REST on Railway HTTPS; no local central fallback |
| `run_wave_c_isolated.sh` | Wave C entry: MQTTS isolation + restore-to-empty + ZAP AF |
| `run_isolated_zap_af.sh` | Disposable authenticated ZAP AF + OpenAPI (pinned digest). Default `OPENFDD_MULTI_TENANT=0`. Wave N: `OPENFDD_MULTI_TENANT=1` seeds acme/building_100/lakeside_sd tenants on the disposable volume. **Never** activeScan live Railway OT. |
| `zap/run_af_disposable.sh` | Wave U U5 Soft-OPEN closer: validate `af_plan.yaml`, optional AF scan when `OPENFDD_ZAP_AF_EXECUTE=1` + env JWT; `--selftest` → **BLOCKED** (never fake High=0). Verdict: `reports/security/zap_af_verdict.json`. |
| `wave_l_ab_isolation_harness.sh` | Tier-2 synthetic Tenant A↔B path + MQTT namespace self-test (no live OT) |
| `wave_l_tip_digest_scan.sh` | Same-sha tip completeness (+ python-absence) |
| `../ops/wave_l_legacy_migrate_dry_run.sh` | L7 legacy-tenant inventory dry-run (refuses APPLY on HTTPS) |
| `restore_to_empty.sh` | Backup → empty volume restore + bounded API budgets |
| `../integration/mqtts_transport_isolation.sh` | Disposable MQTTS cert/ACL/QoS/reconnect |

## Example env

```bash
export OPENFDD_API_BASE=https://openfdd-web-production-af99.up.railway.app
export OPENFDD_ADMIN_PASSWORD=…   # from Railway vars; do not source conflicting local .env
export OPENFDD_MCP_IMAGE=ghcr.io/bbartling/openfdd-mcp:sha-<7>
export EXPECTED_EDGE_ID=pi-1      # optional; else any has_telemetry
# ACCEPT_ZAP_MEDIUM=1 (default) — Medium residuals accepted but recorded
# SKIP_ZAP=1 → required gate SKIPPED → not fully_qualified
./scripts/nightly-ot-bench/run_railway_hub_stress.sh
```

## Wave C isolated (pull GHCR only)

```bash
export OPENFDD_IMAGE_TAG=sha-<7>   # e.g. sha-10d1ec5
./scripts/qualification/run_wave_c_isolated.sh
# or workflow: .github/workflows/wave-c-isolated.yml
```

Field Railway closeout stays public `zap-baseline`. Gate 18 same-volume recreate remains separate from `restore_to_empty.sh`.

## Remaining blockers (honest)

| Blocker | Tier |
|---------|------|
| Viewer password path in `auth_role_matrix.sh` (hub password login exists) | soft / optional |
| Active payload scans / OT write tests | **never** on live hub by default |
| Tightening bounded-perf baselines after CI green week | isolated |

Public claim only after verified evidence: discoverable REST/MCP with automated consistency and permission checks — **not** blanket security certification.
