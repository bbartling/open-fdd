# Data contracts (agent-facing)

Portable artifact shapes agents must respect. Prefer versioned schemas; do not
silently reinterpret old fields when meaning changes.

When `open_fdd.contracts` ships (Milestone A Phase 2), this doc points at those
models. Until then, code truth lives in the paths below.

**Capability ledger:** product capability status for the Vibe 21 recovery
program is machine-readable at
[`docs/migration/react-rust/capabilities.yaml`](../docs/migration/react-rust/capabilities.yaml)
(validated by `scripts/validate_capabilities_ledger.py`). Do not invent
QUALIFIED status without evidence paths.

---

## WattLab dump

| Item | Truth |
| --- | --- |
| Producer | vibe19 / `frontend/web` Export (v3 preferred) |
| Consumer | vibe20 Studio / WattLab loaders |
| Spec pointers | playground vibe19 `docs/PACKAGE_SPEC.md`; vibe20 `DATA_CONTRACT.md` |

Agents must stamp `data_window` / telemetry years on export README so twin
agents see weather year vs bill year mismatches.

---

## Rule result (pandas oracle)

Canonical statuses and shapes come from `open_fdd.rules.base.RuleResult` and
cookbook catalog metadata. Custom rules:

- Use reserved `CUSTOM-*` IDs
- Never override canonical IDs
- Declare required roles, parameters, equipment applicability
- Fail safely
- Excluded from production SQL parity claims unless explicitly migrated

---

## Findings / reporting

`open_fdd.reporting` owns portable builders. Detection ≠ finding — see vibe19
`vibe19-engineering-report` skill. UI owns download buttons and session state.

---

## ECM calculator results

`open_fdd.ecm_engineering` calculators should return enough detail for vibe20
rendering without recomputing formulas (summary + bins/detail + assumptions +
warnings + provenance). Adapters may translate field names only.

Target shape (Phase 4 hardening):

```json
{
  "schema_version": "1",
  "calculator_id": "scheduling_cooling_bins",
  "summary": {
    "baseline_kwh": 0.0,
    "proposed_kwh": 0.0,
    "saved_kwh": 0.0
  },
  "bins": [],
  "assumptions": {},
  "warnings": [],
  "provenance": {}
}
```

---

## Production FDD run

| Item | Truth |
| --- | --- |
| API | `POST /api/fdd/run` (registry / DataFusion) |
| Registry | `sql_rules/registry.yaml` |
| Storage | Arrow / Feather via central |

Agents must not treat pandas oracle output as production FDD execution.

---

## Package append (hourly IoT)

| Item | Truth |
| --- | --- |
| Seed | `POST /api/csv/import/package` |
| Append | `POST /api/csv/import/package/append` with JWT + `confirm: true` |
| Body | `{ building_id, equipment_id, csv }` history_wide chunk |
| Dedup | exact `timestamp` last-write-wins |
| Units | session `unit_system`; FDD converts metric→°F at query |

Do not commit vendor appenders or full Building 50 zips. CI uses `tests/fixtures/hourly_append/`.

Bench orchestrator: [`scripts/csv_flood_afdd_routine_sim.py`](../scripts/csv_flood_afdd_routine_sim.py) — slices `raw_BUILDING_50_openfdd.zip` into hourly appends, applies **AFDD routine** JSON (`openfdd_afdd_routine_v1`: `rule_ids`, `params`, `patches[]` at `append_step`), logs to `reports/eplus-dump/artifacts/csv_flood_sim/`. See [`docs/agent/CSV_FLOOD_AFDD_ROUTINE.md`](../docs/agent/CSV_FLOOD_AFDD_ROUTINE.md).

---

## E+ dump and clustering (`eplus_clustering_v1`)

| Item | Truth |
| --- | --- |
| Online dump | `POST /api/jobs/{id}/wattlab/dumps` (rename to `/eplus/dumps` pending) |
| Offline export | `scripts/eplus_dump_clustering_export.py` → `clustering_features.csv`, timeseries long parquet |
| Artifact root | `EPLUS_DUMP_ROOT` default `reports/eplus-dump/`; legacy `reports/wattlab-parity/` via `scripts/eplus_paths.py` |
| Engine | `tools/wattlab_export/` optional offline Python |

Doc: [`docs/agent/EPLUS_DUMP_CLUSTERING.md`](../docs/agent/EPLUS_DUMP_CLUSTERING.md).

---

## Parity testing (2026-08+)

| Path | Use |
| --- | --- |
| `scripts/synthetic_59_*.py` | Golden 59-rule contract (OpenFDD-only) |
| `scripts/csv_flood_afdd_routine_sim.py` | Real-site BUILDING_50 stream + AFDD routine |
| `scripts/retired/vibe19-parity/` | Retired vibe19 dual-parity (do not run) |
| `scripts/eplus_parity_compare.py` | Dump compare helpers (tests only) |

---

## Building package zip + sidecar maps

Seed lane: `POST /api/csv/import/package`. Layout (generic `AHU_1` / `VAV_1` / `CHW_1` / `weather/`):

```
{building}/
  manifest.json
  {equipment_id}/history_wide.csv
  {equipment_id}/history_wide.json   # or column_map.json — Haystack points
  weather/history_wide.csv           # web-outside-air-temp → web_oa_t
```

- `timestamp_utc` RFC3339 UTC (`Z` or `+00:00`).
- Stamp `equipType` (`ahu` `vav` `chwPlant` `boiler` `heatPump` `weather`). `rtu`→AHU; `heatPump`→HP; UV/FCU air-side→ahu; chillers→chwPlant.
- Sibling JSON `points` keys are Haystack names; ingest translates via `haystack_point_to_role` (`discharge-air-temp` → `sat`). Alias table: [`docs/migration/vibe19/ROLE_MAPPING_PARITY.md`](../docs/migration/vibe19/ROLE_MAPPING_PARITY.md). Authoring: [`docs/agent/PACKAGE_AUTHORING.md`](../docs/agent/PACKAGE_AUTHORING.md).
- **Compact map is normative.** Rich MCP mapping-evidence shapes (`column`/`role`/`confidence`/PROVISIONAL) are SCAFFOLD — see [`docs/modeling/package-schema.md`](../docs/modeling/package-schema.md).
- Empty Overview / RCx / Inspect = missing roles in the zip. Importable ≠ FDD-ready ([`docs/modeling/rule-readiness.md`](../docs/modeling/rule-readiness.md)).
- Heat-pump / WSHP topology and anti-patterns: [`docs/modeling/heat-pump-buildings.md`](../docs/modeling/heat-pump-buildings.md). Do not copy AHU/VAV BUILDING_100 topology onto HP buildings.
- Motor ≠ compressor ≠ valve (status/cmd before amps; never CHW pump / `clg_valve_pct` as compressor proof).
- Sites UI may show CSV / MQTT / Both **inventory labels**; that is not a dual CSV+MQTT writer contract. Unified historian for the same `building_id` remains a later epic.

---

## Units and roles

Role aliases and equipment types: `open_fdd.analytics` / site model helpers and
docs under `docs/rules/cookbook/` + migration [`ROLE_MAPPING_PARITY.md`](../docs/migration/vibe19/ROLE_MAPPING_PARITY.md).
Phase 2 consolidates into shared contracts.

## Equipment type precedence

`equipType` / `equipment_type` is durable package metadata. When present and recognized, it is authoritative for Open-FDD equipment classification; generic equipment-id heuristics are fallback only. `AC_1 + equipType: ahu` must classify as AHU. Keep vendor/campus naming remaps in preprocessors rather than product code.
