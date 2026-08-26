---
title: "Role: package-mapping"
parent: MCP role packs
nav_order: 1
---

# Role pack: `package-mapping` — FDD / mapping engineer

Status: **SCAFFOLD** (spec normative; tools not yet in `mcp/` crate).

## Honesty gate (read first)

The **shipped** package importer consumes **compact** sibling maps:

```json
{ "equipType": "heatPump", "points": { "discharge-air-temp": "da_t" } }
```

See [package-schema.md](../../modeling/package-schema.md) and
[PACKAGE_AUTHORING.md](../../agent/PACKAGE_AUTHORING.md).

The richer entry shape below (`column` / `role` / `unit` / `confidence` /
PROVISIONAL) and the MCP tools in this pack are **not** the live ingest
contract. Do not document or implement as though they already drive Central
import. Until SCAFFOLD tools land, map with compact JSON and existing
`openfdd_csv_import_*` tools.

## Mission

Get a building's historian/point data into Open-FDD with an honest,
evidence-backed **column→role mapping**, using the existing Package lane
(`POST /api/csv/import/package`), so FDD rules and analytics run on correctly
labeled points.

## Scope

**In scope**

- Preflight of building package ZIPs (Haystack/CSV members + mapping JSON).
- Mapping suggestions with per-column evidence (name match, unit, value range,
  Haystack tags).
- Import plan generation and confirmed package import.
- Post-import verification (row counts, coverage, assignment readiness).

**Out of scope**

- Model releases, Unity builds, runtime bundle activation (other roles).
- BACnet reads/writes of any kind.
- Editing FDD rule logic (this role maps points; it does not author rules).
- DM surrogate `feature_spec` — DM features are a fixed product schema, **not**
  historian columns (see `docs/migration/vibe21/MASTER_BUILD.md`).

## Required inputs

1. **Building package ZIP** — CSV/Haystack members accepted by
   `/api/csv/import/package`.
2. **Mapping JSON** (column→role), minimum fields per entry:

| Field | Type | Required | Notes |
|---|---|---|---|
| `column` | string | yes | exact source CSV column header |
| `role` | string | yes | Open-FDD point role ID |
| `unit` | string | yes | declared engineering unit |
| `equip_ref` | string | yes | equipment binding (Haystack ID) |
| `site_ref` | string | yes | site scope |
| `haystack_tags` | string[] | no | supporting tags |
| `confidence` | number 0–1 | no | agent-suggested only; humans may omit |
| `evidence` | string | no | why this mapping (name/unit/range) |

### Package hygiene (agents)

- `timestamp_utc` is RFC3339 UTC: **`Z` or `+00:00`** — both OK. Do not invent vendor clocks in the app.
- String `"equip": "AHU_1"` on a single-equip sidecar is **metadata**, not a nested package map. Nested maps use object `equip`/`equipment`/`devices`.
- Empty charts mean **missing roles** in the zip, not a broken FDD engine. Do not invent site/vendor point names in product code.
- Stamp `equipType` (`ahu` `vav` `chwPlant` `boiler` `heatPump` `weather`). `rtu`→AHU; heatPump→HP; UV/FCU air-side→ahu; chillers→chwPlant.
- Motor ≠ compressor ≠ valve: status/cmd before amps; never CHW pump or `clg_valve_pct` as compressor proof; never motor hours from leave temp.
- Weather sidecar: `{building}/weather/` with `web-outside-air-temp` → `web_oa_t`; `prefer_web_oat`; lat/lon in preprocess.
- Haystack `points` names translate via `haystack_point_to_role`. Alias table: [`ROLE_MAPPING_PARITY.md`](../../migration/vibe19/ROLE_MAPPING_PARITY.md). Authoring: [`PACKAGE_AUTHORING.md`](../../agent/PACKAGE_AUTHORING.md).
- Until SCAFFOLD tools land in `mcp/`, use existing `openfdd_csv_import_*` + `openfdd_csv_package_append`.

## MCP tools

All entries also live in [`tool-catalog.v1.json`](tool-catalog.v1.json).
`bas_write: false` for every tool.

| Tool | Class | Status | Inputs | Outputs | Side effects |
|---|---|---|---|---|---|
| `package_preflight` | read | SCAFFOLD | package ZIP ref (upload ID or workspace path), site_id | member inventory, schema/parse errors, row counts, time range, unit anomalies | none |
| `mapping_suggest` | read | SCAFFOLD | preflight report ID, optional existing mapping JSON | suggested mapping entries with per-column `confidence` + `evidence`, unmapped column list | none |
| `package_import_plan` | plan | SCAFFOLD | package ref, mapping JSON, site_id | signed short-lived plan token, impact summary (points created/updated, rows), warnings | plan record (expires) |
| `package_import_execute` | write | SCAFFOLD | plan token, `confirm:true`, idempotency key | import job ID, per-member result, final mapping revision ID | historian rows + `mappings/{revision}.json` written |
| `mapping_status_get` | read | SCAFFOLD | site_id, optional mapping revision ID | active revision, PROVISIONAL/PROVEN flags per role, assignment coverage | none |

## Workflow

1. **Preflight** — `package_preflight`. Refuse to proceed past unreadable
   members or undeclared units; report, don't guess.
2. **Suggest** — `mapping_suggest`. Every suggestion carries evidence. Columns
   without evidence stay **unmapped** — never invent roles.
3. **Human review** — the engineer edits/accepts the mapping JSON. The agent
   presents diffs; it does not silently overwrite human entries.
4. **Plan** — `package_import_plan`. Surface the impact summary and all
   warnings verbatim.
5. **Confirm import** — `package_import_execute` only with explicit human
   confirmation and the unexpired plan token.
6. **Verify** — `mapping_status_get` + `/api/model/assignments` readiness
   before any rule activation (assignment rule in
   [agent-safety.md](../agent-safety.html)).

## Honesty: PROVISIONAL vs PROVEN

- A mapping entry is **PROVISIONAL** when accepted from suggestion evidence
  only (name/unit/tag heuristics).
- It becomes **PROVEN** only after post-import checks pass: value ranges
  consistent with the role, coverage above threshold, and — where applicable —
  FDD rule parity/screening does not contradict the role.
- Agents must state the PROVISIONAL/PROVEN status whenever citing a mapping,
  and must not present a PROVISIONAL mapping as ground truth in findings or
  reports. Tools return the flag as a structured field.

## Errors and recovery

| Error | Recovery |
|---|---|
| ZIP member unreadable / bad encoding | Report member + byte offset; ask for re-export. Do not import partial packages silently. |
| Duplicate/ambiguous column headers | List collisions; require disambiguation in mapping JSON before planning. |
| Unit conflict (declared vs inferred) | Keep column unmapped; surface both units as evidence; human decides. |
| Plan token expired | Re-run `package_import_plan`; never bypass with a direct write. |
| Import partially failed | Report per-member results; re-run with same idempotency key (idempotent replay), never a blind retry with a new key. |
| Cross-site column reference | Refuse; packages are single-site scoped. |

## Acceptance checklist

- [ ] Preflight ran and its report ID is attached to the import plan.
- [ ] Every imported column has role + unit + equip_ref, or is explicitly unmapped.
- [ ] No mapping entry without recorded evidence or human confirmation.
- [ ] Import executed via plan token + `confirm:true` + idempotency key.
- [ ] `mappings/{revision}.json` exists and revision ID reported to the user.
- [ ] PROVISIONAL/PROVEN status reported per role after post-import checks.
- [ ] Zero BACnet interactions in the session trace.

## Equipment type hygiene

Stamp a generic `equipType` / `equipment_type` whenever the source folder id is opaque. The stamp is persisted by package ingest and wins over id heuristics (`AC_1` + `equipType: ahu` → AHU). Keep vendor/campus remaps in the preprocess repository.
