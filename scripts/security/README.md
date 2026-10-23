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

The active topology IDs are `cloud_portal` and `local_development`.

`cloud_portal` is the current Open-FDD 4.0 product stack. It requires
`openfdd-web` + `openfdd-central` + `openfdd-timescale` (MCP optional) and
forbids `openfdd-mqtt`, `openfdd-fieldbus`, `openfdd-bacnet-modbus`, and
`openfdd-haystack` as runtime services. Its `auth` block requires JWT, multi-tenant
ON, a JWT secret of at least 32 characters, and no open-bind escape hatch. Its
`egress.nf_portal` block keeps the production origin for reference but allows
qualification only against the loopback NF emulator
(`http://127.0.0.1:18089`); real portal connections and NF point writes are
forbidden. The disposable recipe is
[`scripts/qualification/run_portal_qualification.sh`](../qualification/run_portal_qualification.sh)
(see [`scripts/qualification/README.md`](../qualification/README.md)).

`cloud_mqtt_hub`, `ot_local_bacnet_modbus`, and `ot_local_haystack` stay in the
registry with `lifecycle: "archived"` and an `archive_reason`. They describe the
unqualified OT archive (`archive/ot-edge/`). An active profile may not require
or allow an archived wire service or the `mqtt_acl` suite, and evidence for an
archived profile is `BLOCKED` ("cannot qualify a current candidate") unless the
evaluator is called with `allow_archived=True` for archive review.

Evaluate an operator or CI evidence file without contacting a deployment:

```bash
python3 scripts/security/deployment_profile_qualification.py --list-profiles
python3 scripts/security/deployment_profile_qualification.py \
  --profile cloud_portal \
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
  --profile cloud_portal \
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
`--output-dir` `--allow-fixture-writes` `--isolated-jwt-secret-env VAR`.

`--isolated-jwt-secret-env` names an environment variable that holds the
disposable candidate's real JWT secret (`isolated_full` only, at least 32
characters) so the expired-token and sibling-token checks sign with it. The
secret never appears on the command line.

Profiles: `live_readonly`, `isolated_full`, `local_open`.

Credentials use environment variable references from config — never CLI
password arguments and never secrets in fixture JSON.

## Gate verdicts (25 / 25b / 26)

The shell wrappers recompute status from the report or observer file.

- A PASS file written before the probe starts is stale and cannot exit 0.
- Check status ERROR (timeout, connection loss) stays ERROR. It is not relabeled BLOCKED.
- Gate 26 does not exit 0 when the observer says FAIL, or when `ok` is false and `status` is PASS.
- Empty or ack-only HTTP 200 is not an own-object PASS. `live_readonly` accepts a nonempty equipment list. `isolated_full` still requires the seeded canary. An upstream 502 is not described as an empty 200.

These checks are offline. They do not qualify a published image.

## Bounded matrix (Astra C-PY)

Offline planner for authz / IDOR / SSRF / MQTT suite ownership:

```bash
python3 scripts/security/bounded_matrix.py --selftest
python3 scripts/security/bounded_matrix.py --plan --profile isolated_full
```

IDOR is covered by suite **Y** foreign-deny rows. SSRF never probes cloud
metadata; live canary hit-counts use `OPENFDD_SSRF_CANARY_EVIDENCE_JSON` from an
isolated canary server only.

## Suites

- **X** — preauth, login/me, JWT integrity/alg/expiry
- **Y** — A/B own+foreign (IDOR), viewer/admin differences, detector controls,
  and the viewer write matrix: `y.authz.viewer_{import,append,purge,delete}_{own,foreign}_denied`
  (`isolated_full` + `--allow-fixture-writes` only; `NOT_APPLICABLE` elsewhere).
  Each cell sends the write as the viewer (package zip, append JSON,
  `DELETE /api/datasets?building_id=`, `DELETE /api/datasets?id=`) and passes only
  on a structured role deny (`403` + `ok:false`; foreign may be `404`) **and** an
  unchanged owner-visible fingerprint of the target site (`GET /api/datasets` +
  `GET /api/fdd/equipment` as that site's operator) before and after. Central
  routes purge and delete to the same handler; both query forms are probed.
- **Z** — security.txt, CSP, CORS, redirect credential policy, body caps
- **mqtt_acl** — generated tenant ACL fixture + observer (not MQTT continuity); live broker when `OPENFDD_MQTT_ACL_EXECUTE=1`
- **ssrf** — URL fetch policy + isolated canary evidence (optional; never metadata probes)

## Host runtime probe (Astra A10)

Readiness-only (not Nessus). Selftest covers deployment-contract profiles
(`cloud_portal`, archived `cloud_mqtt_hub` / `ot_local_bacnet_modbus` / `ot_local_haystack`, plus legacy
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
