---
name: Open-FDD nightly bug train 3.3.27+
overview: "Master Cursor program index for Open-FDD nightlies 3.3.27→3.3.32: one TODO per child plan in order, each linking the child `.plan.md`. Start only after 3.3.26 closeout is CLOSED."
todos:
  - id: ship-327
    content: Execute [3.3.27 tip pin sync](3.3.27_mqtt_fieldbus_tip_pin_sync.plan.md) — mqtt/fieldbus tip pin or DEFERRED
    status: in_progress
  - id: ship-328
    content: Execute [3.3.28 Lab residual](3.3.28_lab_tuners_econ_ahu_residual.plan.md) — ECON/AHU/VAV Lab leftovers
    status: pending
  - id: ship-329
    content: Execute [3.3.29 viewer/UI](3.3.29_viewer_login_and_ui_scope.plan.md) — viewer login + building scope
    status: pending
  - id: ship-330
    content: Execute [3.3.30 isolated ZAP](3.3.30_isolated_zap_af_auth.plan.md) — authenticated ZAP AF + OpenAPI
    status: pending
  - id: ship-331
    content: Execute [3.3.31 MQTTS](3.3.31_mqtts_transport_isolation.plan.md) — disposable MQTTS ACL/QoS/freshness
    status: pending
  - id: ship-332
    content: Execute [3.3.32 restore/perf](3.3.32_durability_restore_perf.plan.md) — Gate 18 restore + perf budgets
    status: pending
isProject: false
---

# Open-FDD nightly bug train master (3.3.27+)

**Not a VERSION bump itself.** Sequential program: open **one child plan at a time**; mark the matching TODO done only when that child’s BUG_REPORT verdict is CLOSED or DEFERRED with reason.

**Gate:** Finish current closeout first — Verdict 3.3.26 / tip pin (`readme_and_nightly_trains` Cursor plan). Do not start 3.3.27 until then.

**Mirrors:** GitHub is source of truth here; Cursor copies under `~/.cursor/plans/`. Index: [`README.md`](README.md) · handoff: [`../recovery/AI_CONTEXT_HANDOFF.md`](../recovery/AI_CONTEXT_HANDOFF.md).

## Children in order (TODOs)

| Order | Rev | TODO | Child plan | One concern |
|-------|-----|------|------------|-------------|
| 1 | 3.3.27 | `ship-327` | [`3.3.27_mqtt_fieldbus_tip_pin_sync.plan.md`](3.3.27_mqtt_fieldbus_tip_pin_sync.plan.md) | Tip mqtt/fieldbus pin (or honest BLOCKED) |
| 2 | 3.3.28 | `ship-328` | [`3.3.28_lab_tuners_econ_ahu_residual.plan.md`](3.3.28_lab_tuners_econ_ahu_residual.plan.md) | Lab ECON/AHU/VAV residual |
| 3 | 3.3.29 | `ship-329` | [`3.3.29_viewer_login_and_ui_scope.plan.md`](3.3.29_viewer_login_and_ui_scope.plan.md) | Viewer login + building UI scope |
| 4 | 3.3.30 | `ship-330` | [`3.3.30_isolated_zap_af_auth.plan.md`](3.3.30_isolated_zap_af_auth.plan.md) | Isolated authenticated ZAP AF |
| 5 | 3.3.31 | `ship-331` | [`3.3.31_mqtts_transport_isolation.plan.md`](3.3.31_mqtts_transport_isolation.plan.md) | Disposable MQTTS isolation |
| 6 | 3.3.32 | `ship-332` | [`3.3.32_durability_restore_perf.plan.md`](3.3.32_durability_restore_perf.plan.md) | Restore + bounded perf |

```mermaid
flowchart LR
  c326[Verdict_3_3_26]
  c327[3_3_27_tip_pin]
  c328[3_3_28_Lab]
  c329[3_3_29_viewer]
  c330[3_3_30_ZAP]
  c331[3_3_31_MQTTS]
  c332[3_3_32_restore]
  c326 --> c327 --> c328 --> c329 --> c330 --> c331 --> c332
```

## Shared loop (every child)

```text
hygiene START → VERSION bump → one concern → one PR
  → squash-merge → wait GHCR sha-<7>
  → Railway backup → re-pin → x86 fieldbus
  → run_railway_hub_stress.sh LAST → BUG_REPORT → hygiene END
```

Locked: Railway hub + bensbench x86 fieldbus; low-RAM (no local docker build); no Pi / no live OT DoS. Ops: [`../PATCH_CYCLE.md`](../PATCH_CYCLE.md) · [`../STRESS_CLOSEOUT.md`](../STRESS_CLOSEOUT.md) · [`../BUG_REPORT_OT_MODBUS_HAYSTACK.md`](../BUG_REPORT_OT_MODBUS_HAYSTACK.md).

Predecessor: [`openfdd_patch_series_3.3.21_to_3.3.26_program.plan.md`](openfdd_patch_series_3.3.21_to_3.3.26_program.plan.md) (CLOSED when 3.3.26 verdict lands).
