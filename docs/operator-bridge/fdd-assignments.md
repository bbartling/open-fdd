---
title: FDD and assignments
parent: Operator Bridge
nav_order: 7
---

# FDD and assignments

## What the product actually does

Open-FDD separates **data modeling** (BRICK equipment, points, `feeds` relationships) from **rule assignment** (which FDD rules apply to which points, equipment, or BRICK classes). Both are editable in **Model & assignments** and via commissioning JSON import.

### BRICK modeling (integrator + AI-assisted)

| Concern | Where it lives | Notes |
|---------|----------------|-------|
| Equipment tree | `ModelService` + TTL sync | AHU, VAV, sensors; `equipment_type` and `brick_type` on points |
| `brick:feeds` | `model_feeds.py`, `ttl_service.py` | AHU→VAV→zone relationships; used by zone analytics and root-cause hints |
| Point registry | BACnet inventory → model points | `fdd_input` roles (`oa-t`, `stat_zn-t`, …), `series_id` / historian column |
| Commissioning import | `POST /api/model/commissioning-import` | Bulk JSON: sites, equipment, points, optional `fdd_rules` |

**AI Agent** (`agent_tools.py`) can read `slim_brick_graph`, `scope_bundle`, patch rule bindings, and upsert points — but it does **not** auto-generate a full site model without operator review. Expected workflow:

1. BACnet discover/poll populates point registry.
2. Integrator or agent tags `brick_type`, `fdd_input`, and `feeds` on equipment.
3. `POST /api/model/sync-ttl` writes `workspace/data/data_model.ttl`.
4. Model health (`model_health.py`) flags orphan points and missing `fdd_input`.

### Rule assignment (three binding kinds)

Saved rules in `rules_store.json` carry `bindings`:

```json
{
  "point_ids": ["5007-analog-input-1173"],
  "equipment_ids": ["bench-1"],
  "brick_types": ["Outside_Air_Temperature_Sensor"]
}
```

| Binding kind | Effect |
|--------------|--------|
| `point_ids` | Rule runs for that historian point / series |
| `equipment_ids` | Rule runs for all points on equipment (mass bind) |
| `brick_types` | Rule runs for any point with that BRICK class on site |

Assign via:

- **Model & assignments** UI — equipment/point chips, rule pin menu on trend plot
- **Rule Lab** — bindings panel
- **Commissioning import** — `fdd_rules[].bindings` and per-point `fdd_rule_ids`
- **AI Agent** — `patch_rule_binding` tool

Runtime evaluation: `fdd_runner.py` (batch FDD) and `plot_readings.evaluate_fault_plots()` (trend overlays). Plot scope filters rules to those bound to **selected telemetry** (point, equipment, or BRICK class); unbound rules still evaluate site-wide.

### CLASS vs device

- **BRICK class** (`brick_type` on points, or `brick_types` on rule bindings) — template-style assignment (“all `Zone_Air_Temperature_Sensor`”).
- **Device / equipment** (`equipment_id`, BACnet device instance) — instance assignment (“this VAV-12”).
- **Point** (`point_ids`) — single-sensor assignment.

`applies_to` on legacy rules is deprecated; use `bindings` in 3.0+.

## Commissioning JSON shape

Export: `GET /api/model/commissioning-export`. Import accepts `import_ready_json` wrappers (see `commissioningImport.ts`).

Minimum fields integrators/AI should produce:

- `sites`, `equipment[]` with `id`, `equipment_type`, optional `feeds[]`
- `points[]` with `site_id`, `equipment_id`, `brick_type`, `fdd_input`, BACnet IDs
- `fdd_rules[]` with `id`, `source_path` or `code`, `bindings`, `enabled`

After import, verify in **Trend plot** with `?fdd=1` — fault lanes appear on the right-hand 0/1 axis for bound rules.

## Related

- [Model workflow](model-workflow)
- [Rule Lab](rule-lab)
- [Trend plot / fault overlays](dashboard#trend-plot)
