---
name: Open-FDD nightly bug train 3.3.27+
overview: "Program index after 3.3.26 CLOSED. Sequential low-RAM nightlies: mqtt/fieldbus tip sync → Lab ECON/AHU residual → viewer/UI scope → isolated ZAP AF → MQTTS isolation → durability/restore/perf. Each child owns hygiene, GHCR, Railway re-pin, x86 fieldbus, qualification stress LAST, BUG_REPORT. Skip only with DEFERRED."
todos:
  - id: ship-327
    content: Execute 3.3.27 mqtt/fieldbus tip pin sync
    status: pending
  - id: ship-328
    content: Execute 3.3.28 Lab tuners ECON/AHU/VAV residual
    status: pending
  - id: ship-329
    content: Execute 3.3.29 viewer login + UI building scope
    status: pending
  - id: ship-330
    content: Execute 3.3.30 isolated authenticated ZAP AF
    status: pending
  - id: ship-331
    content: Execute 3.3.31 MQTTS transport isolation (disposable)
    status: pending
  - id: ship-332
    content: Execute 3.3.32 durability restore + bounded perf
    status: pending
isProject: false
---

# Open-FDD nightly bug train — 3.3.27+

**Not a shipping VERSION bump.** Program index after series 3.3.21→3.3.26. Open **one child at a time**. Do not start the next until the previous BUG_REPORT verdict is CLOSED or DEFERRED with reason.

Predecessor: [`openfdd_patch_series_3.3.21_to_3.3.26_program.plan.md`](./openfdd_patch_series_3.3.21_to_3.3.26_program.plan.md) (CLOSED when 3.3.26 verdict lands).

## Decisions locked

| Topic | Choice |
|-------|--------|
| Topology | Railway hub (central→mqtt→web) + bensbench **x86 fieldbus** + qualification stress LAST |
| Stress | `run_railway_hub_stress.sh` → cite `qualification_manifest.json` `fully_qualified` |
| Hygiene | 0 open PRs, only `master`, tip Actions green at END |
| Skip | **DEFERRED** row in BUG_REPORT only |
| Non-goals | Pi closeout; local react-ot head-end; local docker build; live OT DoS/activeScan; ML depth reopen |

## Children

| Rev | Plan | One concern |
|-----|------|-------------|
| 3.3.27 | [`3.3.27_mqtt_fieldbus_tip_pin_sync.plan.md`](./3.3.27_mqtt_fieldbus_tip_pin_sync.plan.md) | Tip mqtt/fieldbus pin (or honest BLOCKED) |
| 3.3.28 | [`3.3.28_lab_tuners_econ_ahu_residual.plan.md`](./3.3.28_lab_tuners_econ_ahu_residual.plan.md) | SQL-honest ECON/AHU/VAV/plant Lab leftovers |
| 3.3.29 | [`3.3.29_viewer_login_and_ui_scope.plan.md`](./3.3.29_viewer_login_and_ui_scope.plan.md) | Viewer password identity + building-scoped FDD UX |
| 3.3.30 | [`3.3.30_isolated_zap_af_auth.plan.md`](./3.3.30_isolated_zap_af_auth.plan.md) | Isolated authenticated ZAP AF + OpenAPI |
| 3.3.31 | [`3.3.31_mqtts_transport_isolation.plan.md`](./3.3.31_mqtts_transport_isolation.plan.md) | Disposable MQTTS ACL/QoS/freshness |
| 3.3.32 | [`3.3.32_durability_restore_perf.plan.md`](./3.3.32_durability_restore_perf.plan.md) | Gate 18 restore-to-empty + perf budgets |

## Shared loop

```text
hygiene START → VERSION bump → one concern → one PR
  → squash-merge → wait GHCR sha-<7>
  → Railway backup → re-pin → x86 fieldbus up
  → run_railway_hub_stress.sh LAST → BUG_REPORT → hygiene END
```

Canonical ops: [`PATCH_CYCLE.md`](../PATCH_CYCLE.md) · [`STRESS_CLOSEOUT.md`](../STRESS_CLOSEOUT.md) · [`BUG_REPORT_OT_MODBUS_HAYSTACK.md`](../BUG_REPORT_OT_MODBUS_HAYSTACK.md) · [`scripts/qualification/README.md`](../../../scripts/qualification/README.md).
