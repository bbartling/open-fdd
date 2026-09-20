# Nessus-pass readiness checklist (Wave U U6)

**Claim:** readiness to *pass* a customer/IT Nessus assessment — **not** a fake Nessus PASS.

| Control | Evidence | Status |
|---------|----------|--------|
| Empty/skipped security reports cannot FQ | `tests/security/test_evaluator_integrity_e01_e08.py` | U1 |
| MT ACL/JWT matrix expand | inventory IMPLEMENTED + suite Y | U2 |
| Standalone HTTPS recipe | `docker/compose.standalone.https.yml` + Caddyfile | U3 |
| Fieldbus mgmt fail-closed | default loopback; API key required off-loopback | U3 |
| Exposure manifests | `scripts/security/exposure/*.json` | U3 |
| MQTT private key mode 640 | `services/mqtt/docker-entrypoint-openfdd.sh` | U4 |
| Generated MQTT ACL observer | Soft-OPEN until fixture green (`mqtt-key-mode-tenant-acl`) | U4 |
| ZAP AF plan (no JWT in git) | `scripts/qualification/zap/af_plan.yaml` | U5 Soft-OPEN until disposable run |
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
python3 scripts/security/nessus/import_nessus_report.py --selftest
# When licensed scan exists (private artifact):
python3 scripts/security/nessus/import_nessus_report.py \
  --report /path/to/private.nessus --require-credentialed --out reports/nessus/measured.json
```
