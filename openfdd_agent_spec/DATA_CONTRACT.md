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

## Storage mandate: Timescale/PostgreSQL only (mandatory)

**TIMESCALE/POSTGRESQL ONLY. ONE CANONICAL TELEMETRY WRITE PATH. NO DUAL RECORD WRITING.**

This section is the canonical statement of the storage rule. Root
[`AGENTS.md`](../AGENTS.md), [`AGENTS.md`](AGENTS.md),
[`CONTAINER_AGENT.md`](CONTAINER_AGENT.md), every skill under
[`skills/`](skills/), and every linked doc defer to it. If another doc permits
something this section prohibits, the other doc is wrong: fix the doc, not the
rule.

| Rule | Requirement |
| --- | --- |
| Telemetry store | Timescale on PostgreSQL is the only product store for telemetry. |
| One writer | NF portal REST ingest, NF LAN gRPC history (per-site `transport`) and CSV / package import all call one validated, idempotent Timescale telemetry writer. There is no parallel historian, raw-data mirror, shadow copy, or legacy fallback. |
| No dual record writing | A telemetry record is written once, to Timescale. Never write the same record to a second store (file, object store, cache, second database) for safety, speed, or migration. |
| Prohibited formats and engines | Parquet, Apache Arrow, Arrow IPC, Feather and DataFusion are prohibited in active product storage, caching, execution and dependencies. Only `archive/` may contain them, labeled historical. |
| Derived results | FDD and analytics results (rule results, Overview tables, health matrices, RCx presets, sensor-fault analytics) persist in PostgreSQL tables or live in bounded memory. There is no file-format result cache. |
| Preserved, not telemetry | Haystack RDF / parsed SPARQL, durable job and coverage metadata, audit logs, model snapshots and on-demand exports stay. None of them may become another raw telemetry store: no history read back from an export directory, snapshot, audit log, or job workspace. |
| Python | Python / pandas is tooling only: PyPI `open-fdd`, qualification and tests. Never in the central or web request path. |
| Agent law | Agents follow the canonical spec in `openfdd_agent_spec/`. Skills are authored only in `openfdd_agent_spec/skills/` and synced with `./scripts/openfdd_install_agent_skills.sh --sync`. |

### Enforcement

CI runs `scripts/ci/forbid_columnar_product.py`. It fails when the workspace
dependency graph contains a Parquet, Arrow, DataFusion or Feather crate, when
product Rust names a columnar file or crate path, or when product Rust writes
the `sample` table outside `crates/fdd_tsdb/src/writer.rs`.

### Data revision and FDD result identity

The sample writer records changed ranges in the same transaction as the sample
write. A site `data_revision` advances when that write inserts a row, corrects
a stored row at the same timestamp, or removes a row. An identical replay
leaves the revision and the ranges unchanged. The writer decides that from the
rows the statement returns. It does not use a sum, a count, or `max(ts)`.

One FDD result is the data revision, the model revision, the rule parameters,
the pack version, the half-open window, and the quality and schedule policy.
That identity is `fdd_tsdb::FddResultIdentity`. Changed ranges are
`fdd_tsdb::ChangedRange`, read with `current_data_revision` and
`changed_ranges_after`. Incremental rule execution is a later consumer of this
API.

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

Agent-facing screening context uses schema **`ecm_context_v1`**
(`open_fdd.ecm_engineering.context_envelope.EcmContext`): tenant/building scope,
equipment assets with distinct command/power provenance, roles/DQ, baselines,
scenario, tariff (missing → monetary UNAVAILABLE), calc result + readiness
(`screening` | `validated` | `submission_ready` with human_review for the last),
interactions, and structured `missing_evidence` / `assumptions_required` /
`blocking_issues` / `recommended_measurements`. Combined schedule + fan reset
must apply reset on remaining runtime (`combine_schedule_then_fan_reset`).
Python stays on PyPI — not on central/web request paths.

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

`architecture_epoch: portal-timescale-v1`. Timescale / PostgreSQL only ([storage mandate](#storage-mandate-timescalepostgresql-only-mandatory)). Parquet, Arrow, Feather and DataFusion are prohibited on the product path, not merely "not the historian".

| Item | Truth |
| --- | --- |
| API | `POST /api/fdd/run` (Timescale / PostgreSQL) |
| Registry | `sql/fdd/registry.yaml` |
| Rules | `sql/fdd/postgres/rules/*.sql` |
| Storage | Timescale / PostgreSQL. Rule results persist in PostgreSQL or bounded memory. A file-format result cache is not permitted; the result cache is the PostgreSQL `analytics_result` table. |
| Units | °F canonical. Metric inputs convert at query (`unit_system=metric\|si`). |
| Time | UTC `timestamptz`. Fault duration uses the forward timestamp delta. A gap longer than `MAX_GAP_HOURS` (default 1) is unknown: not fault time and not covered time. |
| Ingest | Normal Framework portal API and CSV packages only |

Agents must not treat pandas oracle output as production FDD execution. `sql_rules/` is the retired DataFusion pack.

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


---

## E+ dump and clustering (`eplus_clustering_v1`)

| Item | Truth |
| --- | --- |
| Online dump | `POST /api/jobs/{id}/wattlab/dumps` (rename to `/eplus/dumps` pending) |
| Offline export | `scripts/eplus_dump_clustering_export.py` → `clustering_features.csv`, timeseries long parquet. Offline Python tooling only; the output is an on-demand export and is never read back as product telemetry. |
| Artifact root | `EPLUS_DUMP_ROOT` default `reports/eplus-dump/`; legacy `reports/wattlab-parity/` via `scripts/eplus_paths.py` |
| Engine | `tools/wattlab_export/` optional offline Python |

Doc: [`docs/agent/EPLUS_DUMP_CLUSTERING.md`](../docs/agent/EPLUS_DUMP_CLUSTERING.md).

---

## Parity testing (2026-08+)

| Path | Use |
| --- | --- |
| `scripts/synthetic_59_*.py` | Golden 59-rule contract (OpenFDD-only) |
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
- Stamp `equipType` (`ahu` `vav` `chwPlant` `boiler` `heatPump` `weather` `zone_other` / `fcu`). `rtu`→AHU; `heatPump`→HP; **unit ventilator / UV → CV AHU** (`ahu`); chillers→chwPlant.
- **ZONE control** (not AHU): fan-coil (`fcu`) with valve PID hunting **or** standalone DDC zone monitor — both get schedule/comfort gate + zone sensor fault equations. See [`docs/modeling/zone-terminals.md`](../docs/modeling/zone-terminals.md).
- Sibling JSON `points` keys are Haystack names; ingest translates via `haystack_point_to_role` (`discharge-air-temp` → `sat`). Alias table: [`docs/migration/vibe19/ROLE_MAPPING_PARITY.md`](../docs/migration/vibe19/ROLE_MAPPING_PARITY.md). Authoring: [`docs/agent/PACKAGE_AUTHORING.md`](../docs/agent/PACKAGE_AUTHORING.md).
- **Compact map is normative.** Rich MCP mapping-evidence shapes (`column`/`role`/`confidence`/PROVISIONAL) are SCAFFOLD — see [`docs/modeling/package-schema.md`](../docs/modeling/package-schema.md).
- Empty Overview / RCx / Inspect = missing roles in the zip. Importable ≠ FDD-ready ([`docs/modeling/rule-readiness.md`](../docs/modeling/rule-readiness.md)).
- Heat-pump / WSHP topology and anti-patterns: [`docs/modeling/heat-pump-buildings.md`](../docs/modeling/heat-pump-buildings.md). Do not copy AHU/VAV BUILDING_100 topology onto HP buildings.
- Motor ≠ compressor ≠ valve (status/cmd before amps; never CHW pump / `clg_valve_pct` as compressor proof).
- Sites UI may show CSV / MQTT / Both **inventory labels**; that is not a dual CSV+MQTT writer contract. Portal and CSV history for the same `building_id` go through the one Timescale telemetry writer ([storage mandate](#storage-mandate-timescalepostgresql-only-mandatory)).

---

## Units and roles

Role aliases and equipment types: `open_fdd.analytics` / site model helpers and
docs under `docs/rules/cookbook/` + migration [`ROLE_MAPPING_PARITY.md`](../docs/migration/vibe19/ROLE_MAPPING_PARITY.md).
Phase 2 consolidates into shared contracts.

## Equipment type precedence

`equipType` / `equipment_type` is durable package metadata and the only classifier for plots, RCx cohorts, overview families, weather selection, motor groups, VAV health, and rule applicability (agent rule 64). A recognized stamp is authoritative (`AC_1` + `equipType: ahu` is an AHU). A missing or unrecognized stamp is unclassified and matches nothing. Do not infer kind from `equipment_id`. Do not prefer a fixture id over the stamp. Do not substring or `LIKE` on `equipment_id` (`RTU_01` must not select `RTU_010`). Plot and cohort filters use the stamp, then exact `equipment_id` equality. Do not hard-code a building id. Do not invent an MQTT delta payload. Id text cannot add or remove equipment that already has a stamp. Parent-AHU id proposals are not cohort membership and are not a plot filter. Keep vendor/campus naming remaps in preprocessors rather than product code. Epic: [#1043](https://github.com/bbartling/open-fdd/issues/1043). Id-substring classification is not a fallback ([#1045](https://github.com/bbartling/open-fdd/issues/1045) PyPI / WattLab, [#1046](https://github.com/bbartling/open-fdd/issues/1046) pandas cohorts, [#1047](https://github.com/bbartling/open-fdd/issues/1047) this spec).

**ZONE vs AHU (do not drift):**

| Stamp | Kind | Notes |
|-------|------|-------|
| `fcu` / `fanCoil` / `zone_other` / `zone` / `standalone_ddc` | `zone_other` | ZONE control — valve PID FCU **or** standalone DDC monitor; comfort + zone sensor FDD |
| `vav` | `vav` | Zone terminal with airflow/damper; same comfort gate for zone-temp rules |
| `unitVentilator` / `uv` / `cv_ahu` | `ahu` | Unit ventilator = **CV AHU** (same thing) |
| `ahu` / `rtu` / `mau` / `doas` | `ahu` | Air handler family |

Never stamp FCU/standalone zone DDC as `ahu`. Never stamp UV as ZONE.
