# Patch trains (Cursor plan mirrors)

These Markdown files are **copies** of Cursor plans under `~/.cursor/plans/` so a dead laptop does not lose the program. **GitHub is source of truth** — edit here first, then mirror to `~/.cursor/plans/`.

## Active — post-3.3.33 soft-OPEN (optimized waves D/E/F + closeout full stress)

Mid-wave = smoke / isolated. **ONE full** Railway stress **LAST** at program closeout → BUG_REPORT. See master.

| Wave | File | Rev / concern |
|------|------|---------------|
| — | [openfdd_post_3.3.33_soft_open_program.plan.md](openfdd_post_3.3.33_soft_open_program.plan.md) | **Master** (waves D/E/F) |
| D | [3.3.34_mqtt_ingest_reconnect.plan.md](3.3.34_mqtt_ingest_reconnect.plan.md) | MQTT ingest reconnect |
| E | [3.3.35_overview_ui_fdd_scope.plan.md](3.3.35_overview_ui_fdd_scope.plan.md) | Overview UI / FDD scope |
| F | [3.3.36_lab_gate_residual.plan.md](3.3.36_lab_gate_residual.plan.md) | Lab residual (honest only) |

## Predecessor — nightly bug train 3.3.27+ (CLOSED through 3.3.33)

Full Railway stress **only** on image-shipping waves (A tip pin, B product tip). Wave C = isolated suites + Railway smoke. See master.

| Wave | File | Rev / concern |
|------|------|---------------|
| — | [openfdd_nightly_bug_train_3.3.27_plus_program.plan.md](openfdd_nightly_bug_train_3.3.27_plus_program.plan.md) | **Master** (waves A/B/C) + 3.3.33 |
| A | [3.3.27_mqtt_fieldbus_tip_pin_sync.plan.md](3.3.27_mqtt_fieldbus_tip_pin_sync.plan.md) | Tip mqtt/fieldbus pin |
| B | [3.3.28_lab_tuners_econ_ahu_residual.plan.md](3.3.28_lab_tuners_econ_ahu_residual.plan.md) | Lab ECON/AHU residual |
| B | [3.3.29_viewer_login_and_ui_scope.plan.md](3.3.29_viewer_login_and_ui_scope.plan.md) | Viewer + UI scope |
| C | [3.3.30_isolated_zap_af_auth.plan.md](3.3.30_isolated_zap_af_auth.plan.md) | Isolated ZAP AF |
| C | [3.3.31_mqtts_transport_isolation.plan.md](3.3.31_mqtts_transport_isolation.plan.md) | MQTTS isolation |
| C | [3.3.32_durability_restore_perf.plan.md](3.3.32_durability_restore_perf.plan.md) | Restore + perf |
| — | [3.3.33_mqtt_overview_csv_parity.plan.md](3.3.33_mqtt_overview_csv_parity.plan.md) | MQTT Overview = CSV |

## Predecessor — 3.3.21→3.3.26 (CLOSED after 3.3.26 verdict)

| File | Rev |
|------|-----|
| [openfdd_patch_series_3.3.21_to_3.3.26_program.plan.md](openfdd_patch_series_3.3.21_to_3.3.26_program.plan.md) | Program index |
| [3.3.21_closeout_railway_stress.plan.md](3.3.21_closeout_railway_stress.plan.md) | Closeout ops |
| [3.3.22_one_dump_ia.plan.md](3.3.22_one_dump_ia.plan.md) | One Dump IA |
| [3.3.23_faults_lab_declutter.plan.md](3.3.23_faults_lab_declutter.plan.md) | Faults/Lab UX |
| [3.3.24_tuners_gl36_wave.plan.md](3.3.24_tuners_gl36_wave.plan.md) | Tuners GL36 |
| [3.3.25_tuners_sv_econ_ahu_wave.plan.md](3.3.25_tuners_sv_econ_ahu_wave.plan.md) | Tuners SV/ECON/AHU |
| [3.3.26_tuners_gates_residual.plan.md](3.3.26_tuners_gates_residual.plan.md) | Qual harness + wrap |

**Ops companions:** [../BENCH_RECOVERY.md](../BENCH_RECOVERY.md) · [../recovery/AI_CONTEXT_HANDOFF.md](../recovery/AI_CONTEXT_HANDOFF.md) · [../BUG_REPORT_OT_MODBUS_HAYSTACK.md](../BUG_REPORT_OT_MODBUS_HAYSTACK.md) · [../../scripts/qualification/README.md](../../scripts/qualification/README.md)
