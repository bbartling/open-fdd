---
title: Rigorous bench scripts
nav_order: 13
---

# Rigorous bench scripts

Maintained on the **Linux edge bench** at `/home/ben/open-fdd`. Upstream copies live in `scripts/` and `tests/selenium/`. See [Bench vs source](../agent/bench-vs-source.html).

## Quick commands

```bash
# Pull nightly + deploy
./scripts/openfdd_bench_pull_latest.sh && source workspace/logs/ghcr_pull_latest.env
NEW_TAG="${OPENFDD_IMAGE_TAG:-nightly}" OPENFDD_RESTORE_HISTORIAN_AFTER_UPDATE=1 ./scripts/openfdd_rust_site_update.sh

# Permanent poll daemon (production-like)
OPENFDD_BACNET_DAEMON_MAX_CYCLES=0 ./scripts/openfdd_bacnet_poll_daemon.sh start

# Standard report → workspace/reports/REV_330_RIGOROUS_TEST_REPORT.md
OPENFDD_BENCH_TAG=nightly ./scripts/openfdd_rigorous_bench_report.sh

# Full matrix (hour test + ZAP when ready)
./scripts/openfdd_rigorous_full_run.sh
```

## Script catalog

| Script | Purpose |
|--------|---------|
| `openfdd_bench_pull_latest.sh` | Pull GHCR (`nightly` → `beta` → semver fallbacks) |
| `openfdd_rigorous_bench_report.sh` | Standard closeout report (#429) |
| `openfdd_rev326_rigorous_report.sh` | Wrapper for above |
| `openfdd_bacnet_poll_daemon.sh` | **Permanent** 60s OT poll loop (default unlimited cycles) |
| `openfdd_polling_feather_validate.sh` | Poll → historian → Feather gate |
| `openfdd_drivers_validate.sh` | Driver smoke (BACnet/Modbus/Haystack/JSON) |
| `openfdd_drivers_rigorous_validate.sh` | Deep validation + PDF artifacts |
| `openfdd_stores_fdd_soak.sh` | Historian growth + FDD validation cycles |
| `openfdd_hour_driver_fault_test.sh` | 60m soak, fault rule change @ minute 30 |
| `openfdd_api_semantic_eval.sh` | RDF / SPARQL / Haystack semantic probes |
| `openfdd_rigorous_full_run.sh` | Orchestrates hour + semantic + rigorous + ZAP |
| `openfdd_soak_pcap_zap_finalize.sh` | Soak, PCAP, OWASP ZAP (Caddy matrix) |
| `openfdd_zap_scan.sh` | ZAP baseline scan |
| `openfdd_zap_caddy_matrix.sh` | ZAP across Caddy HTTP/TLS profiles |
| `openfdd_mcp_eval.sh` | MCP tool surface eval |
| `openfdd_auth_rbac_validate.sh` | Auth RBAC matrix |
| `openfdd_env_bootstrap_validate.sh` | Env / bootstrap contract |
| `openfdd_docker_health_audit.sh` | Container health audit |
| `openfdd_bench_consolidated_report.sh` | Merge artifact dirs into one report |
| `openfdd_rigorous_scripts_bundle.sh` | Sanitized backup tar (bench maintenance) |
| `openfdd_patch_cycle_validate.sh` | Patch-cycle gate for WSL handoff |
| `openfdd_test_failure_triage.sh` | Failure triage helper |
| `tests/selenium/openfdd_frontend_rigorous.sh` | UI regression (Selenium) |

## Phase order (beta sign-off)

1. **GHCR pull** + site update + **start permanent poll daemon**
2. **drivers_validate** — BACnet/Modbus/Haystack green
3. **polling_feather_validate** — samples increment, `.feather` files exist
4. **stores_fdd_soak** — SQL FDD against live `telemetry_pivot`
5. **hour_driver_fault_test** — 60m fault injection
6. **semantic_eval** + **drivers_rigorous** + PDF
7. **ZAP matrix** (#435) — only when 3–4 pass
8. **Selenium** (#434) — UI regression

Report to GitHub [#429](https://github.com/bbartling/open-fdd/issues/429).
