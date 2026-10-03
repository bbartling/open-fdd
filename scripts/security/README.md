# Open-FDD security Python harness

Offline-first tooling to produce **scoped** evidence for authentication, JWT
validation, tenant/role authorization, and selected web deployment controls.
Passing checks mean those named controls held for a specific candidate,
configuration, and fixture set — not that the application is “secure.”

Tip evidence matrix: [`docs/operations/SECURITY_HARNESS_EVIDENCE_3.5.30.md`](../../docs/operations/SECURITY_HARNESS_EVIDENCE_3.5.30.md).

## Layout

| Path | Role |
| --- | --- |
| `openfdd_security/` | Library (stdlib-first) |
| `openfdd_security_probe.py` | CLI |
| `inventory/routes.json` | Route/method inventory + policy disposition (**policy SoT**) |
| `inventory/profile_required_v1.json` | Profile→suite required check IDs (not duplicated in Python) |
| `inventory/cross_cutting_checks.json` | Non-route check IDs allowed in profile required lists |
| `config/example_security_fixtures.json` | Nonsecret example (env refs only) |
| `schemas/` | Report + profile registry versions |
| `fixtures/broken_http.py` | Deliberately broken local HTTP modes for detectors |

## Deployment profiles and exposure evidence

Deployment topology is a separate policy axis from the execution profiles
(`live_readonly`, `isolated_full`, and `local_open`). The canonical contract is
[`schemas/deployment_profiles_v1.json`](schemas/deployment_profiles_v1.json),
and the fail-closed evaluator is
[`openfdd_security/deployment.py`](openfdd_security/deployment.py). It requires
sanitized evidence to bind the source/config/fixture hashes, immutable image
digests, origin, listeners, required services, and explicitly absent services.

The supported topology IDs are `cloud_mqtt_hub`, `ot_local_bacnet_modbus`,
`ot_local_haystack`, and `local_development`. The cloud profile requires
`openfdd-web` + `openfdd-central` + `openfdd-mqtt` and records all OT images as
forbidden. Each OT profile requires Caddy + web + central + exactly one selected
split connector and does not require a local MQTT broker.

Evaluate an operator or CI evidence file without contacting a deployment:

```bash
python3 scripts/security/deployment_profile_qualification.py --list-profiles
python3 scripts/security/deployment_profile_qualification.py \
  --profile cloud_mqtt_hub \
  --evidence /secure/evidence/deployment.json
```

This tool reports `BLOCKED` for missing, stale, contradictory, path-escaping,
or tampered evidence. It does not authorize active scanning, a Railway scan, an
OT request, or a Nessus pass. Start with
[`docs/operations/SECURITY_QUALIFICATION_POLICY.md`](../../docs/operations/SECURITY_QUALIFICATION_POLICY.md)
for the staged acceptance sequence.

The final-image Trivy helper includes both split connector images:
`trivy_ghcr_digests.sh <sha-tag> all` scans `openfdd-bacnet-modbus` and
`openfdd-haystack` alongside central, web, MQTT, the compatibility fieldbus,
MCP, and Caddy. Each output directory records the exact reference in a `.ref`
sidecar; digest-bound candidate evidence still comes from the deployment
profile contract.

**Astra A09 (profile-bound digests / SBOM / provenance):** evaluate a redacted
evidence JSON against a deployment profile without pulling images:

```bash
python3 scripts/security/profile_image_scan.py --selftest
python3 scripts/security/profile_image_scan.py --list-profiles
python3 scripts/security/profile_image_scan.py \
  --profile cloud_mqtt_hub \
  --evidence /secure/evidence/profile_image_scan.json
```

Missing Critical/High, tag-only refs, or “verified because workflow YAML exists”
fail closed. Honest `sbom`/`provenance` ABSENT/NOT_RUN yields **BLOCKED**
(Soft-OPEN), never a fake PASS or signing claim.

## CLI

```bash
# List suites
python3 scripts/security/openfdd_security_probe.py --list-suites

# Dry-run plan (default): no DNS, network, or credential reads
python3 scripts/security/openfdd_security_probe.py \
  --config scripts/security/config/example_security_fixtures.json \
  --base-url http://127.0.0.1:18080 \
  --profile isolated_full \
  --dry-run \
  --output-dir reports/security/dry-run-demo

# Execute against a disposable allowlisted instance
python3 scripts/security/openfdd_security_probe.py \
  --config scripts/security/config/example_security_fixtures.json \
  --base-url http://127.0.0.1:18080 \
  --profile isolated_full \
  --execute --allow-fixture-writes \
  --output-dir reports/security/unique-run-id
```

Flags: `--config` `--base-url` `--profile` `--suite` `--list-suites`
`--dry-run` `--execute` `--max-requests` `--timeout` `--deadline` `--rate`
`--output-dir` `--allow-fixture-writes`.

Profiles: `live_readonly`, `isolated_full`, `local_open`.

Credentials use environment variable references from config — never CLI
password arguments and never secrets in fixture JSON.

## Suites

- **X** — preauth, login/me, JWT integrity/alg/expiry
- **Y** — A/B own+foreign, viewer/admin differences, detector controls
- **Z** — security.txt, CSP, CORS, redirect credential policy, body caps
- **mqtt_acl** — generated tenant ACL fixture + observer (not MQTT continuity); live broker when `OPENFDD_MQTT_ACL_EXECUTE=1`

## Host runtime probe (Astra A10)

Readiness-only (not Nessus). Selftest covers deployment-contract profiles
(`cloud_mqtt_hub`, `ot_local_bacnet_modbus`, `ot_local_haystack`, plus legacy
`standalone_https` / `field_only_ot`). Probe mode inspects listen bind
addresses (loopback vs wildcard), effective SSH `PermitRootLogin` across
`Include` files, and Docker publish-path hints.

```bash
python3 scripts/security/host_runtime_probe.py --selftest
OPENFDD_HOST_RUNTIME_PROBE=1 python3 scripts/security/host_runtime_probe.py \
  --profile ot_local_haystack --out reports/security/host_runtime_probe.json
```

## Standalone HTTPS bootstrap (U3)

```bash
# CI / config lint (no Docker)
python3 scripts/security/peer_probe_https.py --selftest

# Isolated peer soak (official caddy + stub web, self-signed; not Nessus)
OPENFDD_HTTPS_PEER_PROBE=1 ./scripts/security/probe_standalone_https.sh
```

Verdict: `reports/security/standalone_https_probe.json`.

## Offline tests

```bash
python3 -B -m unittest discover -s tests/security -v
```

## Stress wiring (HOLD — do not live-run without authorization)

Gate scripts (IDs, not Wave L script numbers):

- `scripts/nightly-ot-bench/25_security_python_harness.sh` → gate `25_security_python_harness`
- `scripts/nightly-ot-bench/25b_security_post_stress.sh` → gate `25b_security_post_stress`
- `scripts/nightly-ot-bench/26_security_mqtt_acl.sh` → gate `26_security_mqtt_acl` (BLOCKED unless `OPENFDD_MQTT_ACL_EXECUTE=1`; then runs `mqtt_tenant_acl_observer.py`)

Distinct from existing `25_wave_l_tenant_ui_session.sh` (Wave L OFF smoke).

## Requirements

Stdlib only for the harness. Optional pins would go in
`scripts/security/requirements.txt` if added later.


## Inventory honesty (v2)

Dispositions:

- **IMPLEMENTED** — suite actually emits intersecting `implemented_check_ids`
- **PLANNED** — check IDs reserved; **not tested yet**
- **BLOCKED_POLICY** — policy unresolved; cannot claim PASS

Never use COVERED. See `inventory/implemented_checks.json` and
`tests/security/test_inventory_integrity.py`.

## Burp Suite / ZAP vs this harness

| Concern | Prefer |
| --- | --- |
| Tenant A/B isolation, JWT alg/expiry, role deny matrices, security.txt/CSP/CORS regression | **This harness** (X/Y/Z) — must stay **broader and more repeatable than a human Burp click-path** on those controls |
| Passive URL crawl / High finding baseline | ZAP in `run_railway_hub_stress.sh` |
| Authenticated active scan, novel payloads, UI-driven AF | Soft-OPEN Kali / Burp (`kali-zap-af`) — not replaced by this probe |

Do not claim the probe “replaces Burp” or that Python is universally superior.
Honest division: this harness owns **repeatable** multi-tenant authz/authn /
JWT / role matrices for CI and Soft-OPEN gates; ZAP/Burp/Kali still own
active-scan breadth and exploratory AF. Operator path:
[`docs/operations/TESTBED_TAKEOVER.md`](../../docs/operations/TESTBED_TAKEOVER.md).
