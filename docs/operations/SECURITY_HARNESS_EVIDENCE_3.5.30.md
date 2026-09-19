# Security harness evidence — 3.5.30

Requirement → evidence matrix for the Python security probe (gates **25** / **25b** / **26**)
and Wave S1 tip closeout. Product FDD remains DataFusion SQL; this harness is
qualification evidence only — not a “100% secure” claim.

| Audit § | Requirement | Evidence |
| --- | --- | --- |
| §1 Inventory | Unique check IDs; PLANNED / IMPLEMENTED / BLOCKED_POLICY (no COVERED) | `scripts/security/inventory/routes.json` + `implemented_checks.json`; `tests/security/test_inventory_integrity.py` |
| §2 Python tools | CLI + profiles + redaction | `scripts/security/openfdd_security_probe.py`; `tests/security/` offline layers |
| §3 X/Y/Z | Core authn / authz / deploy probes | `scripts/security/openfdd_security/suites/__init__.py` (S1 expands anon401 datasets/rules/mapping + foreign datasets/mapping deny) |
| §4 Evaluate A/B/C | Offline units + Layer C Rust | `python3 -m unittest discover -s tests/security`; CI `preauth_disclosure` |
| §5 Legacy runners | Gates required in hub stress | `scripts/nightly-ot-bench/run_railway_hub_stress.sh` (25/25b required; 26 N/A unless MQTT ACL) |
| §6 Fail closed | Dry-run ≠ PASS; High ZAP never accepted | Gate scripts + `zap_risk_dispositions.json` (Medium rule-specific only) |
| §7 Tip cycle | GHCR pin + MEGA FQ | Tip `sha-<7>` / VERSION **3.5.30**; stress artifact filled at closeout below |

## Live hub execute

| Item | Value |
| --- | --- |
| Profile | `live_readonly` |
| Config | `scripts/security/config/railway_hub_security_fixtures.json` |
| Env | `OPENFDD_SECURITY_EXECUTE=1` |
| Gate 26 | N/A unless `OPENFDD_SECURITY_MQTT_ACL=1` |

## Closeout (fill after FQ MEGA)

| Item | Value |
| --- | --- |
| Hub health | _TBD_ `3.5.30+…` |
| Tip image | _TBD_ `sha-<7>` |
| Stress dir | _TBD_ `reports/nightly-ot-bench_<TS>/` |
| `fully_qualified` | _TBD_ |
| Backup | _TBD_ |

## Soft-OPEN (not tip blockers)

- ACME `oa_t` duplicate canonical reject (`vim-1` edge catalog) — Soft-OPEN
- Local BACnet FEC Soft-OPEN
- Kali authenticated ZAP AF / MQTT ACL staging
