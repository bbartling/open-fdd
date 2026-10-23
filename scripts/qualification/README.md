# Qualification harness (entry point)

## Protocol connector closeout (Phase 5D)

`protocol_connector_qualification.py` is the bounded, fail-closed evidence
entry point for the split Rust connector program. It writes only a small JSON
record and `SUMMARY.md`; credentials, response bodies, endpoint details, and
process logs are never copied into the artifacts.

Run the offline contract and evaluator negatives in CI or on a low-RAM bench:

```bash
python3 scripts/qualification/protocol_connector_qualification.py --selftest
python3 scripts/qualification/protocol_connector_qualification.py \
  --stage synthetic --require-stage synthetic \
  --report-dir reports/protocol-connector-qualification
```

The split image/recipe gate emits a redacted evidence file when
`OPENFDD_SPLIT_EVIDENCE_DIR` is set. CI evaluates it after the gate:

```bash
OPENFDD_SPLIT_EVIDENCE_DIR="$RUNNER_TEMP/protocol-connector-split-evidence" \
  bash scripts/gates/protocol_connector_split.sh
python3 scripts/qualification/protocol_connector_qualification.py \
  --stage image_recipe \
  --evidence "$RUNNER_TEMP/protocol-connector-split-evidence/image_recipe.json" \
  --require-stage image_recipe
```

This gate records local image IDs as immutable build evidence. A local image ID
does not claim a published GHCR manifest digest; GHCR publication, SBOM,
provenance, signing, and vulnerability results must be recorded separately
when those Actions are available.

The BACnet and Haystack stages accept only a redacted operator evidence JSON
file. They require every bounded check and a recent timezone-aware timestamp.
Missing, stale, partial, contradictory, receipt-mismatched, historian-missing,
`SKIP`, and `BLOCKED` evidence cannot qualify. BACnet evidence must be
read-only and must halt when device reachability fails. Haystack evidence must
identify the trusted catalog/auth mode without exposing credentials and must
prove the committed Central receipt plus historian readback. No endpoint,
credential, host, or device is assumed by this script.

Each live `PASS` also has a check-specific evidence contract. BACnet records
must identify device instance 5007, prove read-only counters, typed point and
present-value counts, a priority-array read, a bounded non-overlapping priority
history visit, restart recovery with persisted history, and request/time bounds.
Haystack records must prove a trusted catalog, Basic or SCRAM authentication
from secure local configuration, successful bounded `about`/`nav`/current/
history reads, typed timestamps and units, a committed receipt correlated to
the expected message, canonical historian sample readback, replay with zero
duplicates and rejected changed parameters, restart/resume, and zero UDP or
BACnet route surfaces. Missing proof is `BLOCKED`; measured violations are
`FAIL`. These are evidence fields only and do not hard-code a device into the
Rust product.

**Profiles**

| Profile | Entry | Environment |
|---------|-------|-------------|
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
`26_security_mqtt_acl` when required by the runner. MQTT continuity (21),
telemetry pause/resume (35), and MQTTS gap blame (39) are transport evidence,
not broker authorization tests. Gate 39 prints EDGE / TRANSIT / RAILWAY /
SPARSE_OK / INCONCLUSIVE; exit 2 is BLOCKED (missing probe), not a pass.
All-N/A security remains `NOT_APPLICABLE`; no security evidence remains
`null`. Dry-run harness artifacts cannot fully qualify.

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
| `protocol_connector_qualification.py` | Phase 5D split image/recipe and read-only bench evidence evaluator; fail-closed selftest |
| `write_manifest.py` | Create / record / finalize / selftest |
| `zap_baseline_verdict.py` | Parse ZAP JSON; High always fails; Medium explicit |
| `run_portal_qualification.sh` | Disposable `cloud_portal` qualification: central + web + Timescale + loopback NF emulator, two tenants, security harness, historian side-effect proof (see below) |
| `lib/portal_stack.sh` | Shared disposable-stack helpers: per-run secrets, unique compose project, project-scoped teardown |
| `portal/portal_qual.py` · `portal/nf_emulator.py` | Docker-free plan / package / verdict helpers and the stdlib NF emulator (fixture `fixtures/nf_emulator/points.json`) |
| `run_wave_c_isolated.sh` | Wave C entry on the portal profile: portal qualification + restore-to-empty + ZAP AF |
| `run_isolated_zap_af.sh` | Astra C-ZAP wrapper: mint a disposable `cloud_portal` candidate (multi-tenant ON, per-run JWT secret) via `lib/portal_stack.sh`, run the broken-credential negative control, then call `zap/run_af_disposable.py` against `http://web:8080`. Scanner credential is a private file, never argv. Digest-pinned ZAP. **Never** activeScan Railway or a site; no fallback crawl. |
| `zap/run_af_disposable.py` | Single ZAP AF evaluator: exact disposable origin checked before any credential is read; anchored scope; scanner-origin `/api/auth/me` probes before/during/after the scan proven from ZAP's exported message history; strict typed alert parsing; per-instance Medium dispositions with expiry; write-once raw report + SHA-256; wall-clock and request budgets with owned cleanup. `--selftest` → **BLOCKED**; `--negative-control` must reject a broken scanner credential. Execute via `OPENFDD_ZAP_AF_EXECUTE=1`. |
| `zap/run_af_disposable.sh` | Thin shell alias to `run_af_disposable.py`. |
| `restore_to_empty.sh` | Portal stack: `pg_dump` + workspace tarball → fresh volumes → restore; proves the fixture site's Timescale count + md5, total samples, workspace manifest, control-plane files, admin API identity state, and operator login; then bounded API budgets |

## Disposable portal qualification (`cloud_portal`)

GHCR images only (never a local build). Requires Docker with Compose >= 2.24.4,
`curl`, `jq`, and `python3`. Pick the newest published tag by OCI `created`:

```bash
./scripts/ghcr_newest_by_created.py openfdd-central openfdd-web
export OPENFDD_IMAGE_TAG=sha-<7>        # same tag for central and web
./scripts/qualification/run_portal_qualification.sh
# optional: ARTIFACT_DIR=/path/to/out  OPENFDD_TIMESCALE_IMAGE=timescale/timescaledb@sha256:...
```

What one run does:

1. Generates a `qa<YYYYMMDD><4hex>` prefix and a unique compose project
   `openfdd-qual-portal-<prefix>`. Generates a 48-byte JWT secret, the hub
   admin password, and the Timescale password into a 0600 env file under a
   0700 temp dir. Secrets reach curl only through header/body files and
   are scrubbed from artifacts.
2. Starts `docker/compose.portal.yml` + `compose.timescale.yml` +
   `compose.portal-qual.yml`. Central and Timescale sit on an internal network
   with no host port and no internet route. Web listens on `127.0.0.1:<free port>`.
   The NF emulator shares central's network namespace at
   `http://127.0.0.1:18089`, the only provider origin configured. No real
   portal credentials or connections exist.
3. Creates tenants A and B plus a viewer and an operator per tenant through
   `/api/admin/*`. The admin identity is the env hub admin, because file users
   cannot be admin; the run asserts that a tenant-admin upsert is rejected.
4. Seeds one canary package per tenant, waits for Timescale rows and NF
   emulator samples, and checks that the emulator saw reads and zero point writes.
5. Runs the security harness (`isolated_full`, X/Y/Z, viewer write matrix)
   with `--isolated-jwt-secret-env`. It then proves that both tenants'
   Timescale count + md5 did not change.
6. Writes `verdict.json` (`portal_qualification_v1`) and tears down only its
   own project: `down --remove-orphans` (no `-v`), then removes volumes
   labelled with that project name. It never prunes.

Exit codes: `0` PASS, `1` FAIL (any step FAIL/ERROR), `2` BLOCKED (no failures,
but some checks unverified). Against `sha-c83ea9b` the harness reports 0 FAIL /
0 ERROR and 14 BLOCKED `y.authz.a_own_*` positive controls: the canary package
has one equipment row, so datasets mapping, FDD results/series and the plant
analytics have no own content to prove a 200 against.

Not covered by the local recipe: the profile's https origin and port-443
listener evidence come from the deployed edge, not from this loopback run.

## Wave C isolated (pull GHCR only)

```bash
export OPENFDD_IMAGE_TAG=sha-<7>
./scripts/qualification/run_wave_c_isolated.sh
```

Runs `run_portal_qualification.sh`, `restore_to_empty.sh`, and
`run_isolated_zap_af.sh` in order, each in its own disposable project, and
aggregates the verdicts (`wave_c_isolated_v2`). There is no MQTT step; the
broker belongs to the archived OT profile.

Field Railway closeout stays public `zap-baseline`. Gate 18 same-volume recreate remains separate from `restore_to_empty.sh`.

## Remaining blockers (honest)

| Blocker | Tier |
|---------|------|
| Active payload scans / OT write tests | **never** on live hub by default |
| Tightening bounded-perf baselines after CI green week | isolated |

Public claim only after verified evidence: discoverable REST/MCP with automated consistency and permission checks — **not** blanket security certification.
