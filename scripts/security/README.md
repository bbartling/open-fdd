# Open-FDD security Python harness

Offline-first tooling to produce **scoped** evidence for authentication, JWT
validation, tenant/role authorization, and selected web deployment controls.
Passing checks mean those named controls held for a specific candidate,
configuration, and fixture set — not that the application is “secure.”

## Layout

| Path | Role |
| --- | --- |
| `openfdd_security/` | Library (stdlib-first) |
| `openfdd_security_probe.py` | CLI |
| `inventory/routes.json` | Route/method inventory + policy disposition |
| `config/example_security_fixtures.json` | Nonsecret example (env refs only) |
| `schemas/` | Report + profile registry versions |
| `fixtures/broken_http.py` | Deliberately broken local HTTP modes for detectors |

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
- **mqtt_acl** — optional isolated broker ACL (not MQTT continuity)

## Offline tests

```bash
python3 -B -m unittest discover -s tests/security -v
```

## Stress wiring (HOLD — do not live-run without authorization)

Gate scripts (IDs, not Wave L script numbers):

- `scripts/nightly-ot-bench/25_security_python_harness.sh` → gate `25_security_python_harness`
- `scripts/nightly-ot-bench/25b_security_post_stress.sh` → gate `25b_security_post_stress`
- `scripts/nightly-ot-bench/26_security_mqtt_acl.sh` → gate `26_security_mqtt_acl` (optional/BLOCKED without broker fixture)

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
