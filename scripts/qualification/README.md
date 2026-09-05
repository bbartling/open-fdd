# Qualification harness (entry point)

**Profiles**

| Profile | Entry | Environment |
|---------|-------|-------------|
| `railway_field` | `./scripts/nightly-ot-bench/run_railway_hub_stress.sh` | Live Railway hub + x86 fieldbus (read-oriented; light ZAP) |
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

## Scripts

| Script | Role |
|--------|------|
| `write_manifest.py` | Create / record / finalize / selftest |
| `zap_baseline_verdict.py` | Parse ZAP JSON; High always fails; Medium explicit |
| `auth_role_matrix.sh` | anon/admin/operator(/viewer) REST checks |
| `railway_mcp_accuracy.sh` | MCP↔REST on Railway HTTPS; no local central fallback |
| `run_wave_c_isolated.sh` | Wave C entry: MQTTS isolation + restore-to-empty + ZAP AF |
| `run_isolated_zap_af.sh` | Disposable authenticated ZAP AF + OpenAPI (pinned digest) |
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
