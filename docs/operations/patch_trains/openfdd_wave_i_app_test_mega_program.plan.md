---
name: openfdd Wave I app-test mega program
overview: "GitHub mirror of Cursor wave_i_app_test_mega_master — basic app MEGAs first, ONE full Railway stress at closeout."
todos:
  - id: follow-cursor-master
    content: Execute via .cursor/plans/wave_i_app_test_mega_master.plan.md and children
    status: pending
isProject: false
---

# Wave I — app-test MEGA program (repo mirror)

**Canonical execution plan:** [`.cursor/plans/wave_i_app_test_mega_master.plan.md`](../../../.cursor/plans/wave_i_app_test_mega_master.plan.md)

**Evidence:** [`BUG_REPORT_OT_MODBUS_HAYSTACK.md`](../BUG_REPORT_OT_MODBUS_HAYSTACK.md) · agent_spec rules **55–58**.

Children (Cursor):

1. `wave_i_lakeside_read_csv` — basic FDD
2. `wave_i_overview_tables_unfiltered` — basic Overview
3. `wave_i_data_model_json_export` — basic Data Model
4. `wave_i_plot_full_span_b100` — plot span
5. `mqtt_dual_oat_wave_a209637a` — MQTT dual OAT
6. `wave_i_stress_gates_enhance` — harness
7. Master I7 — **ONE** `run_railway_hub_stress.sh`

Deferred: `mqtt_monitor_sse_782` (#782).
