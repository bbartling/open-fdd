# Nessus-pass readiness checklist (Wave U U6)

**Claim:** readiness to *pass* a customer/IT Nessus assessment — **not** a fake Nessus PASS.

| Control | Evidence | Status |
|---------|----------|--------|
| Empty/skipped security reports cannot FQ | `tests/security/test_evaluator_integrity_e01_e08.py` | U1 |
| MT ACL/JWT matrix expand | inventory IMPLEMENTED + suite Y | U2 |
| Standalone HTTPS recipe | `docker/compose.standalone.https.yml` + Caddyfile (HTTP redir-only) | U3 **CLOSED** |
| Standalone HTTPS peer probe | `scripts/security/peer_probe_https.py` (--selftest CI; `OPENFDD_HTTPS_PEER_PROBE=1` soak) | U3 **CLOSED** |
| Fieldbus mgmt fail-closed | default loopback; API key required off-loopback; unit tests in `services/fieldbus/src/main.rs` | **CLOSED U3** |
| Exposure manifests | `scripts/security/exposure/*.json` | U3 |
| MQTT private key mode 640 | `services/mqtt/docker-entrypoint-openfdd.sh` | U4 |
| Generated MQTT ACL observer | `scripts/security/mqtt_tenant_acl_observer.py` + gate 26 (`OPENFDD_MQTT_ACL_EXECUTE=1`) · fixture `scripts/security/fixtures/mqtt_tenant_acl/` | U4 CLOSED |
| ZAP AF plan + disposable runner (no JWT in git/artifacts) | `af_plan.yaml` + `run_isolated_zap_af.sh` · PASS High=0 disposable `20260920T150920Z` | **U5 CLOSED** |
| Trivy final-image digests | `scripts/security/trivy_ghcr_digests.sh` | U6 |
| Nessus importer + synthetic fixtures | `scripts/security/nessus/` | U6 |
| **Real licensed Nessus on isolated host** | `.nessus` import Critical/High=0 | **BLOCKED Soft-OPEN** |

## Acceptance policy (pre-declared)

- Critical/High: **0** unresolved  
- Medium: time-bound disposition JSON (owner, expiry, rationale)  
- Never: invent `.nessus`, disable TLS checks, rename Trivy as Nessus  

## Commands

```bash
python3 -B -m unittest discover -s tests/security -v
python3 -B -m unittest tests.qualification.test_zap_af_disposable -v
# ZAP AF Soft-OPEN: hygiene selftest exits BLOCKED (not PASS)
./scripts/qualification/zap/run_af_disposable.sh --selftest
python3 scripts/security/nessus/import_nessus_report.py --selftest
python3 scripts/security/peer_probe_https.py --selftest
# Optional isolated Compose soak (official caddy + stub web; no product image builds):
OPENFDD_HTTPS_PEER_PROBE=1 ./scripts/security/probe_standalone_https.sh
# MQTT tenant ACL observer (content + key-mode; live mosquitto when Docker OK):
OPENFDD_MQTT_ACL_EXECUTE=1 ./scripts/nightly-ot-bench/26_security_mqtt_acl.sh
# When licensed scan exists (private artifact):
python3 scripts/security/nessus/import_nessus_report.py \
  --report /path/to/private.nessus --require-credentialed --out reports/nessus/measured.json
# Disposable authenticated ZAP AF (JWT via env only — never argv):
# OPENFDD_ZAP_AF_EXECUTE=1 ZAP_TARGET_ORIGIN=http://… \
#   ZAP_AUTH_HEADER_VALUE="Bearer …" ./scripts/qualification/zap/run_af_disposable.sh
```
