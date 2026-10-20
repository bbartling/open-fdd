# Legacy tooling purge — 2026-10-20

Branch `chore/purge-legacy-tooling`, rebased onto `origin/master` `1d6c4ff9` (#1306 archive of OT protocols, plus #1305 data-safe Timescale).

Scope: Open-FDD 4.0 ingest is the Normal Framework portal API and CSV only. This removes 3.x stress / MEGA gates, ACME/Railway stress
harnesses, OT-edge update helpers, and stale one-off scripts from product `scripts/` and `tests/` paths, plus runbook docs that only
described them. #1306 already moved OT protocol code and the nightly bench into `archive/ot-edge/unmaintained/`. Those archive copies stay.
This rebase does not delete anything under `archive/`.

Kept after the rebase (no longer deleted outright):

| Path | Why it stays |
|------|----------------|
| `archive/ot-edge/unmaintained/**` copies of the nightly bench, fieldbus acceptance scripts, and `test_mqtts_gap_blame.py` / `test_wave_ik_acme_building.py` | #1306 archived them. Product paths stay gone. |
| `scripts/gates/afdd_slice_identity.py` | #1306 moved it out of `scripts/nightly-ot-bench/`. `scripts/gates/afdd_schedule_upsert_contract.sh` still runs it. |
| `scripts/openfdd_workspace_reset_default.sh` | #1305 made it the data-safe workspace reset. `scripts/test_data_safe_defaults.sh` calls it. |

Still deleted from the product tree: `scripts/migrate/dry_run_migration_report.sh` (one-off driver-tree cutover; the migrator it called now lives in the archive) and `tests/security/test_real_gate_wrappers.py` (tests of the archived nightly gates 25/25b). `tests/qualification/test_write_manifest.py` keeps `test_railway_runner_requires_both_gate36_variants` and reads the archived runner.

The table below is the original product-path deletion list (188 files: scripts 178, tests 4, docs 6). `tools/`: 0. Rows whose product path #1306 archived are gone from `scripts/` and `tests/` and present under `archive/ot-edge/unmaintained/`.

## Deleted paths

| Path | Reason |
|------|--------|
| `docs/agent/CSV_FLOOD_AFDD_ROUTINE.md` | Runbook for deleted AFDD flood sim |
| `docs/agent/wsl-product-gh-actions-deep-sleep-prompt.md` | Runbook for deleted WSL GH-actions deep-sleep watcher |
| `docs/operations/HISTORIAN_SCALE_QUALIFICATION.md` | Runbook for deleted historian scale harness |
| `docs/operations/RAILWAY_VALIDATION_752.md` | Runbook for deleted 752 gate |
| `docs/operations/WAVE_L_LEGACY_MIGRATE_CHECKLIST.md` | Runbook for deleted Wave L migrate dry-run |
| `docs/operations/WAVE_M_AFDD_FLOOD.md` | Runbook for deleted gate 2N AFDD flood |
| `scripts/agent_wattlab_dump.sh` | Deprecated alias/wrapper (points at successor or missing script) |
| `scripts/audit_no_hardcoding.sh` | Superseded by audit_no_private_bench_hardcoding.sh (CI) |
| `scripts/bench_5007_long_smoke.sh` | Deprecated alias/wrapper (points at successor or missing script) |
| `scripts/bench/openfdd_bacnet_poll_daemon.sh` | Bench BACnet poll daemon / stores soak / pcap capture (3.x OT bench) |
| `scripts/bench/openfdd_stores_fdd_soak.sh` | Bench BACnet poll daemon / stores soak / pcap capture (3.x OT bench) |
| `scripts/bench/README.md` | Bench BACnet poll daemon / stores soak / pcap capture (3.x OT bench) |
| `scripts/bench/run_bacnet_pcap_capture.sh` | Bench BACnet poll daemon / stores soak / pcap capture (3.x OT bench) |
| `scripts/compare_synthetic_slice.py` | Unreferenced Aug one-off SQL/fixture generator |
| `scripts/csv_flood_afdd_routine_sim.py` | AFDD CSV flood simulator + its routine fixture (3.x stress) |
| `scripts/download_ahu_fixtures.sh` | Unreferenced June/July one-off |
| `scripts/fieldbus/bench.env.example` | Fieldbus BACnet bench/smoke/soak/pcap harness for the archived OT edge; no CI/code refs |
| `scripts/fieldbus/bench_lib.sh` | Fieldbus BACnet bench/smoke/soak/pcap harness for the archived OT edge; no CI/code refs |
| `scripts/fieldbus/bench_test.sh` | Fieldbus BACnet bench/smoke/soak/pcap harness for the archived OT edge; no CI/code refs |
| `scripts/fieldbus/openfdd_bench_gate.sh` | Fieldbus BACnet bench/smoke/soak/pcap harness for the archived OT edge; no CI/code refs |
| `scripts/fieldbus/openfdd_platform_driver.sh` | Fieldbus BACnet bench/smoke/soak/pcap harness for the archived OT edge; no CI/code refs |
| `scripts/fieldbus/pcap_validate_docker.sh` | Fieldbus BACnet bench/smoke/soak/pcap harness for the archived OT edge; no CI/code refs |
| `scripts/fieldbus/pcap_validate.sh` | Fieldbus BACnet bench/smoke/soak/pcap harness for the archived OT edge; no CI/code refs |
| `scripts/fieldbus/preflight_free_47808.sh` | Fieldbus BACnet bench/smoke/soak/pcap harness for the archived OT edge; no CI/code refs |
| `scripts/fieldbus/run_dev.sh` | Fieldbus BACnet bench/smoke/soak/pcap harness for the archived OT edge; no CI/code refs |
| `scripts/fieldbus/smoke_test.sh` | Fieldbus BACnet bench/smoke/soak/pcap harness for the archived OT edge; no CI/code refs |
| `scripts/fieldbus/soak_test.sh` | Fieldbus BACnet bench/smoke/soak/pcap harness for the archived OT edge; no CI/code refs |
| `scripts/fixtures/b50_afdd_routine.json` | AFDD CSV flood simulator + its routine fixture (3.x stress) |
| `scripts/gates/afdd_oom_regression.sh` | Gate 37/38/47 OOM / memory-stress evaluator for nightly bench |
| `scripts/gates/combined_ot_synth_validate.sh` | 3.x OT/MQTTS→Feather E2E scaffolds |
| `scripts/gates/creekside_package_import_spot.sh` | Railway/ACME stress spot-check gates driven by run_railway_hub_stress |
| `scripts/gates/e2e_mqtts_feather.md` | 3.x OT/MQTTS→Feather E2E scaffolds |
| `scripts/gates/e2e_mqtts_smoke.sh` | 3.x OT/MQTTS→Feather E2E scaffolds |
| `scripts/gates/gate47_eval_artifacts.py` | Gate 37/38/47 OOM / memory-stress evaluator for nightly bench |
| `scripts/gates/product_smoke_softopen.py` | Railway/ACME stress spot-check gates driven by run_railway_hub_stress |
| `scripts/gates/product_smoke_softopen.sh` | Railway/ACME stress spot-check gates driven by run_railway_hub_stress |
| `scripts/gates/railway_b100_parity_spot.sh` | Railway/ACME stress spot-check gates driven by run_railway_hub_stress |
| `scripts/gates/railway_validation_752_gate.py` | Railway/ACME stress spot-check gates driven by run_railway_hub_stress |
| `scripts/gates/ui_fdd_rcx_backend_probe.py` | DataFusion-era Overview/FDD/RCx backend comb (DataFusion removed in 4.0) |
| `scripts/gates/ui_fdd_rcx_validate.sh` | DataFusion-era Overview/FDD/RCx backend comb (DataFusion removed in 4.0) |
| `scripts/historian_scale_check.py` | H10 DataFusion/Parquet-era historian scale harness (workflow already removed) |
| `scripts/historian_scale_generate.py` | H10 DataFusion/Parquet-era historian scale harness (workflow already removed) |
| `scripts/historian_scale_workloads.sql` | H10 DataFusion/Parquet-era historian scale harness (workflow already removed) |
| `scripts/inject_sql_fan_gate.py` | Unreferenced Aug one-off SQL/fixture generator |
| `scripts/inject_sql_remaining_gates.py` | Unreferenced Aug one-off SQL/fixture generator |
| `scripts/integration/local_fieldbus_acceptance.sh` | Local fieldbus acceptance/compose check harness; no CI refs |
| `scripts/integration/local_fieldbus_compose_check.sh` | Local fieldbus acceptance/compose check harness; no CI refs |
| `scripts/make_metric_history_twin.py` | Unreferenced Aug one-off SQL/fixture generator |
| `scripts/materialize_phase6_wave1_fixtures.py` | Unreferenced Aug one-off SQL/fixture generator |
| `scripts/migrate/backup_pre_cutover.sh` | One-off driver_tree→fieldbus cutover backup/dry-run (pre-3.x cutover) |
| `scripts/migrate/dry_run_migration_report.sh` | One-off driver_tree→fieldbus cutover backup/dry-run (pre-3.x cutover) |
| `scripts/nightly-ot-bench/00_pull_ghcr_up.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/01_health_gates.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/02_bacnet_ot.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/03_mqtt_parquet_persist.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/04_modbus_ot.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/05_haystack.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/06_csv_fdd_sql.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/07_cloud_sim.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/08_weather_trend.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/09_rest_ot.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/10_dual_mqtt_signoff.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/10_react_spa.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/11_bacnet_pcap_fp_scan.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/11_dashboard_apis_549.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/12_parity_honesty_550.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/13_mcp_accuracy.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/14_capability_ledger.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/15_product_truth_honesty.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/16_playwright_web.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/17_synthetic_health_matrix_fault_hours.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/18_volume_restore_smoke.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/19_engineering_bundle_validate.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/20_wave_i_app_test_megas.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/21_wave_k_app_test_megas.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/22_wave_l_tenant_mode.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/23_wave_l_parquet_isolation.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/24_capacity_pressure.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/24_wave_l_mqtts_namespace.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/25b_security_post_stress.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/25_security_python_harness.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/25_wave_l_tenant_ui_session.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/26_security_mqtt_acl.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/26_wave_l_tenant_budgets.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/27_wave_l_ab_isolation.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/28_wave_l_legacy_migrate_dry_run.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/2N_wave_m_afdd_flood.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/30_wave_m_durable_session.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/31_wave_n_tenant_acl.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/32_wave_n_mqtts_continuity.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/33_wave_o_admin_datamodel_acl.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/34_wave_o_security.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/35_mqtt_telemetry_pause_resume.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/36_model_ecm_qualification.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/36_mv_sql_oracle_twin.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/37_acme_analytics_charts.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/38_acme_afdd_qualification.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/39_mqtts_gap_blame.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/40_no_id_heuristics.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/42_cache_retention_preview_health.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/43_overview_browser_analytics.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/44_run_now_latency_budget.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/45_analytics_planning_comb.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/46_data_model_integrity.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/47_mid_request_memory_shed.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/afdd_slice_identity.py` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/bench.env.example` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/field_devices.bench.example.toml` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/field_devices.diy_router_lab.example.toml` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/field_devices.railway.example.toml` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/fixtures/gate19_seed/BUILDING_100/AHU_1/history_wide.csv` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/fixtures/gate19_seed/BUILDING_100/AHU_1/history_wide.json` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/fixtures/gate19_seed/BUILDING_100/manifest.json` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/fixtures/gate19_seed/BUILDING_100/session_config.json` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/lib_capacity_sample.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/lib_pick_edge.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/lib_security_gate.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/lib.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/mqtts_gap_blame.py` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/README.md` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/rest_sim.py` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/run_all.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/run_railway_hub_stress.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/run_tip_sequential.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/test_37_json_envelope.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/test_afdd_evaluator_negatives.py` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/nightly-ot-bench/test_pick_edge.sh` | 3.x nightly OT/Railway stress + MEGA gate suite (ACME/MQTTS/BACnet bench, gates 00–47); not run by any 4.0 CI |
| `scripts/openfdd_auth_smoke.sh` | June 3.x one-hour live validation cluster (sources a missing smoke_live_fdd_validation.sh) |
| `scripts/openfdd_bench_extend_disk.sh` | One-off bench/agent babysit helpers (PR #475, issue #429, LVM extend) |
| `scripts/openfdd_ci_babysit_pr.sh` | One-off bench/agent babysit helpers (PR #475, issue #429, LVM extend) |
| `scripts/openfdd_csv_append_validation.sh` | June 3.x one-hour live validation cluster (sources a missing smoke_live_fdd_validation.sh) |
| `scripts/openfdd_csv_lake_geneva_validate.sh` | Unreferenced June/July 3.x CSV lab one-offs |
| `scripts/openfdd_csv_preflight.sh` | Unreferenced June/July 3.x CSV lab one-offs |
| `scripts/openfdd_driver_poll_1m.sh` | Issue #402 3.x BACnet/Haystack driver one-offs |
| `scripts/openfdd_fieldbus_railway_up.sh` | bensbench fieldbus→Railway MQTTS edge bring-up / MQTT edge-kit restore (OT edge update tooling) |
| `scripts/openfdd_haystack_bacnet_parity.sh` | Issue #402 3.x BACnet/Haystack driver one-offs |
| `scripts/openfdd_issue402_rust_pdf.sh` | Issue #402 3.x BACnet/Haystack driver one-offs |
| `scripts/openfdd_login_ui_smoke.sh` | June 3.x one-hour live validation cluster (sources a missing smoke_live_fdd_validation.sh) |
| `scripts/openfdd_one_hour_validation_report.sh` | June 3.x one-hour live validation cluster (sources a missing smoke_live_fdd_validation.sh) |
| `scripts/openfdd_product_gh_actions_watch.sh` | One-off bench/agent babysit helpers (PR #475, issue #429, LVM extend) |
| `scripts/openfdd_product_ghcr_deep_sleep.sh` | One-off bench/agent babysit helpers (PR #475, issue #429, LVM extend) |
| `scripts/openfdd_restore_edge_kit.sh` | bensbench fieldbus→Railway MQTTS edge bring-up / MQTT edge-kit restore (OT edge update tooling) |
| `scripts/openfdd_ui_smoke.sh` | June 3.x one-hour live validation cluster (sources a missing smoke_live_fdd_validation.sh) |
| `scripts/openfdd_validation_workspace_reset.sh` | June 3.x one-hour live validation cluster (sources a missing smoke_live_fdd_validation.sh) |
| `scripts/openfdd_workspace_reset_default.sh` | Unreferenced June/July 3.x CSV lab one-offs |
| `scripts/ops/bacpypes3_whois_smoke.py` | BACnet OT LAN bench smoke (ops one-off) |
| `scripts/ops/crash_watch_central.sh` | Soft-OPEN 370/371 memory/ingest/receipt soak + crash-watch stress harness |
| `scripts/ops/local_bacnet_ot_bench.sh` | BACnet OT LAN bench smoke (ops one-off) |
| `scripts/ops/local_memory_ingest_bench.py` | Soft-OPEN 370/371 memory/ingest/receipt soak + crash-watch stress harness |
| `scripts/ops/prove_receipt_watermark_50k.py` | Soft-OPEN 370/371 memory/ingest/receipt soak + crash-watch stress harness |
| `scripts/ops/railway_compact_hub.sh` | Parquet hive compaction for the Railway ACME/OT hub (Timescale in 4.0) |
| `scripts/ops/run_local_memory_ingest_bench.sh` | Soft-OPEN 370/371 memory/ingest/receipt soak + crash-watch stress harness |
| `scripts/ops/run_t6a_local_qual.sh` | Soft-OPEN 370/371 memory/ingest/receipt soak + crash-watch stress harness |
| `scripts/ops/test_local_memory_ingest_bench.sh` | Soft-OPEN 370/371 memory/ingest/receipt soak + crash-watch stress harness |
| `scripts/ops/wave_l_legacy_migrate_dry_run.sh` | Wave L/N/U one-off host/migration helpers |
| `scripts/ops/wave_n_agent_bridge_tokens.sh` | Wave L/N/U one-off host/migration helpers |
| `scripts/ops/wave_n_auth_validate_host.sh` | Wave L/N/U one-off host/migration helpers |
| `scripts/ops/wave_n_push_pr_host.sh` | Wave L/N/U one-off host/migration helpers |
| `scripts/ops/wave_u_v7_tenant_path_migrate.sh` | Wave L/N/U one-off host/migration helpers |
| `scripts/parity_phase0_react_capture.cjs` | Unreferenced Phase-0/UXR screenshot capture one-off |
| `scripts/qualification/auth_role_matrix.sh` | Qualification gates invoked only by the nightly/Railway stress runners |
| `scripts/qualification/mv_sql_oracle_twin_gate.py` | Qualification gates invoked only by the nightly/Railway stress runners |
| `scripts/qualification/railway_mcp_accuracy.sh` | Qualification gates invoked only by the nightly/Railway stress runners |
| `scripts/qualification/railway_smoke_wave_c.sh` | Qualification gates invoked only by the nightly/Railway stress runners |
| `scripts/qualification/wave_l_ab_isolation_harness.sh` | Qualification gates invoked only by the nightly/Railway stress runners |
| `scripts/qualification/wave_l_tip_digest_scan.sh` | Qualification gates invoked only by the nightly/Railway stress runners |
| `scripts/retired/vibe19-parity/materialize_b100_sql_parity_fixtures.py` | Retired vibe19 dual-parity tooling (self-labelled do-not-run) |
| `scripts/retired/vibe19-parity/materialize_vav_oracle_fixtures.py` | Retired vibe19 dual-parity tooling (self-labelled do-not-run) |
| `scripts/retired/vibe19-parity/README.md` | Retired vibe19 dual-parity tooling (self-labelled do-not-run) |
| `scripts/retired/vibe19-parity/wattlab_parity_ofdd_rust_bundle.py` | Retired vibe19 dual-parity tooling (self-labelled do-not-run) |
| `scripts/retired/vibe19-parity/wattlab_parity_ofdd_rust_capture.py` | Retired vibe19 dual-parity tooling (self-labelled do-not-run) |
| `scripts/retired/vibe19-parity/wattlab_parity_oracle_dump.py` | Retired vibe19 dual-parity tooling (self-labelled do-not-run) |
| `scripts/synthetic_59_health_matrix_fault_hours_soak.py` | Synth59 Overview/health-matrix/target-pair soak (3.x stress) |
| `scripts/synthetic_59_overview_analytics_soak.py` | Synth59 Overview/health-matrix/target-pair soak (3.x stress) |
| `scripts/synthetic_59_stage.py` | Synth59 Overview/health-matrix/target-pair soak (3.x stress) |
| `scripts/synthetic_59_target_pair_soak.py` | Synth59 Overview/health-matrix/target-pair soak (3.x stress) |
| `scripts/timescale/spa_softopen_proxy.py` | Broken file (a pasted log line, not Python); unreferenced |
| `scripts/uxr00_capture.cjs` | Unreferenced Phase-0/UXR screenshot capture one-off |
| `scripts/validate_mzvav_csv_pipeline.sh` | Unreferenced June/July one-off |
| `scripts/verify_rust_auth_smoke.sh` | Unreferenced June/July one-off |
| `scripts/vibe21_regen_golden_grid.py` | Unreferenced vibe21 one-offs (turnkey targets react-ot) |
| `scripts/vibe21_turnkey_openfdd.sh` | Unreferenced vibe21 one-offs (turnkey targets react-ot) |
| `scripts/wattlab_parity_watch_ghcr.py` | Deprecated alias/wrapper (points at successor or missing script) |
| `scripts/wave_g_lab_tuner_parity_apply.py` | Unreferenced Aug one-off SQL/fixture generator |
| `tests/qualification/test_mqtts_gap_blame.py` | Tests of deleted nightly-ot-bench gates (MQTTS gap blame / Wave I-K ACME MEGAs) |
| `tests/qualification/test_wave_ik_acme_building.py` | Tests of deleted nightly-ot-bench gates (MQTTS gap blame / Wave I-K ACME MEGAs) |
| `tests/security/test_gate36_qualification_verdict.py` | Replays jq finalizer of deleted nightly gate 36 |
| `tests/security/test_real_gate_wrappers.py` | Tests of deleted nightly gates 25/25b/26 wrappers |

## Reference edits (dangling pointers removed)

- `scripts/gates/afdd_schedule_upsert_contract.sh` (CI via `run_all_gates.sh --quick`): dropped the `require` lines that pointed at `nightly-ot-bench/38_acme_afdd_qualification.sh`. It still runs `python3 scripts/gates/afdd_slice_identity.py`. The Rust-source contract checks remain.
- `scripts/audit_no_private_bench_hardcoding.sh`: allowlist entries for deleted paths removed.
- `tests/qualification/test_write_manifest.py`: `test_railway_runner_requires_both_gate36_variants` reads `archive/ot-edge/unmaintained/scripts/nightly-ot-bench/run_railway_hub_stress.sh`.
- `scripts/ghcr_watch_central.py`: wake prompt no longer tells agents to run the synth59 soak.
- `.gitignore`, `AGENTS.md`, `frontend/web/README.md`, `mcp/INSTRUCTIONS.md`, `mcp/README.md`, `openfdd_agent_spec/{AGENTS,CONTAINER_AGENT,DATA_CONTRACT,HAYSTACK_RDF_ROLLOUT,PR_PROTOCOL}.md`,
  skills `openfdd-{package-mapping,stack-ghcr,railway-cli,bacnet-ot-debug}`, `scripts/{qualification,security}/README.md`, the mqtt_tenant_acl fixture README,
  `tools/open-fdd-modernization/OPENFDD_CODEBASE_MAP.md`, the workspace smoke-profile example, and current docs under `docs/` (agent, drivers, web-app, mcp-agents, migration/vibe21,
  modeling, operations) had lines or links to deleted scripts and docs removed.
- Left as-is: historical records (`docs/archive/**`, `SESSION_LOG.md`, `patch_trains/`, `BUG_REPORT_*`, `REMOTE_BRANCH_AUDIT_*`, `SECURITY_HARNESS_EVIDENCE_*`, `recovery/AI_CONTEXT_HANDOFF.md`).

## Kept, borderline (and why)

| Path | Why kept |
|------|----------|
| `.github/workflows/bacnet-mqtt-container-integration.yml`, `.github/workflows/wave-c-isolated.yml` + `scripts/integration/{bacnet_mqtt_container_smoke,mqtts_transport_isolation}.sh`, `scripts/qualification/run_wave_c_isolated.sh`, `tests/security/test_bacnet_mqtt_ci_key_modes.py` | CI references them, and they belong with the field-container code that the archive PR moves. Both workflows skip on 4.0 because openfdd-fieldbus and openfdd-mqtt are not published. Retire them with the archive PR. |
| `scripts/openfdd_bacnet_nic_setup.sh` | `rust-ci.yml` checks it with `test -x` / `bash -n`. This is OT edge host setup. Drop it together with the CI lines. |
| `scripts/release/smoke_standalone_mqtts.sh`, `scripts/gates/{no_anonymous_mqtt,sole_bacnet_udp_owner,mqtt_contract_unit,architecture_no_central_fieldwire}.sh`, `scripts/ops/render_selected_ot_https.sh` | Run by CI (`run_all_gates`, rust-ci, ghcr stack, rust-release). They are MQTT/OT guards. |
| `scripts/security/{mqtt_tenant_acl_observer.py,fixtures/mqtt_tenant_acl/**,field_only_exposure.py,validate_ot_compose_selection.py,exposure/field_only_ot.json}` + their tests | Coupled into the security harness (`openfdd_security/suites`, `host_runtime_probe.py`). `tenants.json` is read by central tests. The appsec unittests run them. |
| `scripts/migrate_driver_tree_to_fieldbus.py` | Hint string in `edge/src/drivers/bacnet.rs` (edge code is kept). |
| `scripts/openfdd_drivers_validate.sh`, `scripts/openfdd_health_check.sh` | `mcp/src/bridge.rs` and `edge/src/server.rs` reference them. |
| `scripts/openfdd_stack_{lib,pull,up}.sh`, `openfdd_caddy_smoke.sh`, `openfdd_csv_{import,export}_sidecar.sh`, `test_openfdd_stack_image_tag.sh` | CI syntax and regression jobs use them. |
| `scripts/railway_repin_hub.sh`, `railway_central_workspace_backup.sh`, `openfdd_railway_release.sh`, `ops/assert_hub_env_after_repin.sh`, `ops/capture_railway_central_logs.sh` | Railway central/web ops. A Railway re-pin is in flight in the main tree. |
| `scripts/stress/**`, `scripts/lessons/**`, `scripts/softopen/**`, `scripts/timescale/**`, `scripts/nf/**` | Current 4.0 Timescale / SPARQL / NF tooling (Oct 2026). `stress/helpers.py` is being edited in the main tree. |
| `scripts/qualification/{restore_to_empty.sh,run_isolated_zap_af.sh,zap/**}` | Central and web restore plus authenticated ZAP. Appsec unittests cover them. |
| `scripts/check_ghcr_tip_python_absence.sh`, `release/smoke_react_web_image.sh`, `openfdd_demo_gate.sh`, `openfdd_disk_preflight.*`, `openfdd_maint_update_resume.sh`, `openfdd_docker_maintenance.sh`, `openfdd_data_retention_sidecar.sh`, `ops/kickoff_grok_bot.py` | Generic image/ops utilities. Kept scripts, examples or AGENTS docs still point at them. |
| `scripts/wattlab_parity_diff.py` (deprecated alias), `eplus_*`, `vibe21_master_build.sh`, `vibe21_export_champion_portable.py` | A test uses the alias, and central runtime hints reference the vibe21 scripts. |
| `tools/**` | `wattlab_export` (CI PYTHONPATH), `python_oracle` (cookbook-parity CI), `react_parity` (fixtures used by `phase2_shadow_compare.py` in CI), and the `open-fdd-modernization` / `open-fdd-vibe21-production` plan docs (heavily linked). |
| `tools/wattlab_export/agent_afdd.py` | Kept. The broken `--schedule` argument is restored. `smoke_standalone_mqtts.sh` (CI) requires the file to exist. Offline tooling, not the product request path. |

## Follow-ups for Ben

- Retire the legacy runbook docs in a docs pass: `docs/operations/{STRESS_CLOSEOUT,BENCH_RECOVERY,PATCH_CYCLE,TESTBED_TAKEOVER}.md`, `docs/central-fieldbus-cutover.md`, and skill `openfdd-stress-closeout`. They still describe the deleted nightly/Railway stress loop and `openfdd_fieldbus_railway_up.sh`, and about 30 files link to them.
- `docs/operations/LOCAL_BACNET_BACPYPE3_BENCH.md` (kept with the field lane) still mentions the deleted `scripts/ops/local_bacnet_ot_bench.sh` / `bacpypes3_whois_smoke.py` / `scripts/fieldbus/preflight_free_47808.sh`.
