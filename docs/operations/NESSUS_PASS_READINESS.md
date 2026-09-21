# Nessus-pass readiness checklist (Wave U U6)

**Status: REOPENED acceptance, 2026-09-20.** This checklist defines readiness work; it is not evidence that a customer assessment will pass. Complete license-free checks now for both standalone and field-only OT profiles. Only the actual licensed assessment is BLOCKED. See [milestones](../../MILESTONES.md), [Wave U master](WAVE_U_MASTER.md) and [the audit rows in BUG_REPORT](BUG_REPORT_WAVE_P.md).

Component delivery and historical scans remain useful, but the independent acceptance audit found gaps in deployment and evaluator evidence. Do not close readiness from an importer selftest, stub TLS test, earlier candidate or completed image scan with unresolved required findings.

| Control | Evidence | Status |
|---------|----------|--------|
| Evaluated qualification, required gates and provenance | E01–E08 plus additional negative/healthy evaluator and wrapper tests | PARTIAL; UA-01/03/04/06/07 open |
| MT ACL/JWT matrix expand | inventory IMPLEMENTED + suite Y | U2 |
| Standalone HTTPS recipe | Resolved supported Compose configuration + candidate images | REOPENED UA-02 |
| Standalone HTTPS peer probe | Actual application from a second peer, trusted CA/hostname, measured exposure | REOPENED UA-02; existing stub/selftest is component evidence |
| Fieldbus mgmt fail-closed | default loopback; API key required off-loopback; unit tests in `services/fieldbus/src/main.rs` | **CLOSED U3** |
| Exposure manifests | `scripts/security/exposure/*.json` | U3 |
| MQTT private key mode 640 | `services/mqtt/docker-entrypoint-openfdd.sh` | U4 |
| Generated MQTT ACL observer | Candidate broker + real provisioner + healthy allowed/denied observers | REOPENED UA-03/08 |
| Authenticated ZAP and private artifacts | Candidate/identity/job coverage and evaluated runner outcomes | REOPENED UA-04 |
| Image findings and final digests | All profile components, scanner/DB versions, SBOM, remediation + rescan | REOPENED UA-05; scan acquisition alone is insufficient |
| Nessus importer + synthetic fixtures | Per-host credentialed/completeness and negative-case validation | REOPENED UA-06; requires no scanner license |
| Field-only deployment and effective key permissions | Profile manifest, host/runtime and product-generated kit tests | REQUIRED UA-08 |
| Standalone/field Linux host checks | OS/kernel/packages, SSH, Docker exposure, firewall, permissions and restart/restore | REQUIRED; image checks do not assess the host |
| **Real licensed Nessus on isolated host** | `.nessus` import Critical/High=0 | **BLOCKED Soft-OPEN** |

## Acceptance policy (pre-declared)

- Critical/High: **0** unresolved  
- Medium: time-bound disposition JSON (owner, expiry, rationale)  
- Never: invent `.nessus`, disable TLS checks, rename Trivy as Nessus  

Evaluate external port/TLS exposure, credentialed host configuration, container runtime and final-image findings separately. Use synthetic OT peers on an isolated representative host for invasive application tests. Test IPv4/IPv6 and Docker publication rules from a peer; a manifest is expected exposure, not a scan result. Root/privilege exceptions need a documented purpose and measured behavior.

Actual Nessus acceptance later also requires expected targets/policy/ports, per-host completed checks, successful credentialed Linux evidence, scanner/feed versions, timestamps, candidate mapping and private report hash. Plugin 19506 presence alone does not establish successful credentials. Tenable may stop after discovering OT services when OT scanning is disabled; verify completeness before interpreting zero findings. See [Tenable discovery settings](https://docs.tenable.com/nessus/Content/DiscoverySettings.htm) and [credentialed-check evidence](https://docs.tenable.com/whitepapers/useful-plugins/Content/UsefulPlugins/TroubleshootingPlugins.htm).

## Commands

The commands below are existing entry points. Their current PASS labels remain subject to the reopened acceptance criteria; repair/evaluate the tooling before using it to close readiness. Run active tools only on the defined isolated target. No license is needed for Python, TLS/exposure, host, image or importer fixture checks.

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
