---
title: AI-assisted energy calculations
parent: Data modeling
nav_order: 8
---

# AI-assisted energy engineering (export → LLM → import)

After the **Brick / BACnet data model** is in place ([AI-assisted data modeling](ai_assisted_tagging), [LLM workflow](llm_workflow)), you can use the same **export → external LLM → import** pattern for **site-scoped energy / savings calculation specs**. Each building keeps its own rows in Postgres; the API also serializes them into `config/data_model.ttl` as `ofdd:EnergyCalculation` with `brick:isPartOf` the site.

**Predefined calculators** (labels, parameter keys, units) are versioned in the platform (`openfdd_stack.platform.energy_calc_library`). The UI on **Energy Engineering** mirrors them; the LLM must **only** use `calc_type` values and **parameter keys** that appear in the export bundle.

**Default FDD penalty narratives (18)** — Engineering descriptions, difficulty ordering, and suggested `calc_type` mappings are in [Default FDD energy penalty catalog](energy_penalty_equations). You can **materialize** them as disabled rows with **`POST /energy-calculations/seed-default-penalty-catalog?site_id=<uuid>`** (or **Seed default penalty catalog** in the UI), then enable and fill parameters / `point_bindings` per site. Seeded rows use `external_id` values `penalty_default_01` … `penalty_default_18` and may include `_penalty_catalog_seq` in `parameters`; the TTL emitter adds **`ofdd:penaltyCatalogSeq`** for SPARQL.

---

## Two-phase workflow (data model, then energy)

1. **Phase A — Data model** — `GET /data-model/export` → LLM tagging → `PUT /data-model/import` so equipment, points, `external_id`, and Brick types exist for the site. See [AI-assisted data modeling](ai_assisted_tagging) and [LLM workflow](llm_workflow).
2. **Phase B — Energy** — `GET /energy-calculations/export?site_id=<uuid>` → LLM fills or edits calculation rows → `PUT /energy-calculations/import` with body `{ "site_id": "<same uuid>", "energy_calculations": [ ... ] }`. Optionally seed the 18 penalty templates first (UI or seed endpoint above).

Always pass the **same `site_id`** as in the header site selector (or UUID from `GET /sites`). Calculations are **never** global.

---

## Export bundle (`GET /energy-calculations/export`)

Query parameter: **`site_id`** (required, UUID).

Response (JSON):

| Field | Purpose |
|--------|---------|
| `format` | `openfdd_energy_calculations_v1` — version tag for agents. |
| `site_id`, `site_name` | Scope for the LLM. |
| `exported_at` | ISO timestamp. |
| `calc_types` | Same structure as `GET /energy-calculations/calc-types` — **embeds** every allowed calculator with `id`, `label`, `summary`, `category`, and `fields[]` (`key`, `label`, `type`, `min`/`max`, `default`, `options` for enums). |
| `penalty_catalog` | Same 18 objects as **`GET /energy-calculations/penalty-catalog`** (`seq`, `layer`, `difficulty`, `name`, `fdd_trigger`, `math_summary`, `calc_type`, `default_parameters`) — reference for agents; see [energy penalty equations](energy_penalty_equations). |
| `energy_calculations` | Existing rows: `id`, `external_id`, `name`, `description`, `calc_type`, `parameters`, `point_bindings`, `enabled`, `equipment_id`, **`equipment_name`** (resolved for display), timestamps. |

Download this JSON from **Energy Engineering** (“Download export JSON”) or call the API from an agent.

---

## Import body (`PUT /energy-calculations/import`)

Top-level keys (**only** these — `extra=forbid` on the body model):

- **`site_id`** (UUID string) — must match the site you are editing.
- **`energy_calculations`** (array) — rows to **create or update** by **`(site_id, external_id)`**.

Each row:

| Field | Required | Notes |
|--------|-----------|--------|
| `external_id` | yes | Stable slug per site; primary upsert key with `site_id`. |
| `name` | yes | Human label. |
| `calc_type` | yes | Must be one of the `calc_types[].id` values from the export. |
| `parameters` | no | Object; keys must match the `fields[].key` for that `calc_type`. Use numeric JSON numbers for floats. |
| `point_bindings` | no | **Object** mapping **semantic keys** (e.g. `cfm`, `kw`) to **point `external_id`** strings. Must be a JSON object (not `[]` or a primitive); omit or use `{}` if empty. Stored and exported to TTL; preview library may not consume every binding yet. |
| `enabled` | no | Default `true`. |
| `equipment_id` | no | UUID of equipment on this site. |
| `equipment_name` | no | Alternative to `equipment_id`: resolved under `site_id`. Fails with 400 if the name does not exist — **create equipment on Data Model BRICK first**. |

Unknown keys on each row are **ignored** so you can paste rows straight from an export (e.g. `id`, `created_at`) without hand-stripping.

**Upsert behavior:** If `external_id` already exists for the site, the row is **updated** (including `calc_type`, `parameters`, `enabled`, equipment link). Otherwise a new row is inserted.

---

## LLM prompt template (copy-paste) {#energy-calc-llm-prompt}

Use as **system** or **developer** instructions when transforming the export JSON into import JSON.

```text
You are assisting with Open-FDD energy / savings calculation specs for ONE building site.

The user will paste JSON from:
GET /energy-calculations/export?site_id=<uuid>

That JSON includes:
- calc_types[] — the ONLY allowed calc_type string ids and the ONLY valid parameter keys per type.
- penalty_catalog[] (when present) — 18 default FDD penalty narratives; use for context or to align copy with site-specific rows (optional for import output).
- energy_calculations[] — existing saved rows (may be empty).

Your job is to return ONLY valid JSON with EXACTLY these two top-level keys:

{
  "site_id": "<same uuid string as in the export>",
  "energy_calculations": [ ... ]
}

Rules:
- Do not return markdown, comments, or extra top-level keys.
- Preserve site_id from the export unless the user explicitly asks to change site (normally never).
- Each energy_calculations[] element must include: external_id, name, calc_type, parameters, enabled (boolean).
- calc_type MUST be one of calc_types[].id from the export.
- parameters MUST use only keys listed in calc_types[].fields for that calc_type. Use JSON numbers for numeric fields.
- Use equipment_name (string) to attach a calc to equipment when the export lists equipment names from the data model; use null equipment_id/equipment_name only for site-level calcs.
- point_bindings: optional **JSON object** (not an array or null as the value) mapping semantic keys to point **external_id** strings from the data model (e.g. `{ "cfm": "OA_FLOW_SCFM" }`). Use `{}` or omit the key if there are no bindings. Only reference external_ids that exist in the user's data model export if they provided one.
- For annualized / M&V style estimates, use hours and rates consistent with the field labels in calc_types (e.g. hours_fault, electric_rate_per_kwh).
- If job context is missing (which faults, which equipment), prefer conservative parameters or ask a short clarifying question in plain language WITHOUT emitting JSON in that turn.

When returning JSON, the object must parse as Open-FDD PUT /energy-calculations/import.
```

---

## Agents and HTTP context

- **`GET /model-context/docs`** — Regenerated doc bundle for RAG-style agents; include updates to this page when rebuilding.
- **OpenAPI** — `/openapi.json` or `/docs` lists export/import paths alongside data-model tools.

---

## UI: tree and row actions

On **Energy Engineering** (Energy calculations tab), calculations appear under **Site-level** or under each **equipment** node. Use the **row actions** control (⋮) for **Enable**, **Disable**, or **Delete**, or **right-click** the row (same interaction model as **Points**). The **Equipment metadata** tab edits per-equipment engineering fields that feed the penalty catalog and TTL (`equipment.metadata.engineering`); align with [Data model engineering](../howto/data_model_engineering).

---

## See also

- [AI-assisted data modeling](ai_assisted_tagging) — Phase A (Brick / points).
- [LLM workflow](llm_workflow) — Canonical data-model prompt and validation habits.
- [Default FDD energy penalty catalog](energy_penalty_equations) — 18 seeded templates, TTL `ofdd:penaltyCatalogSeq`, Open-Meteo / rates notes.
- [Data model engineering](../howto/data_model_engineering) — Equipment `engineering` metadata and TTL / SPARQL.
- [Frontend — Energy Engineering](../frontend#energy-engineering) — Tree, seed defaults, row actions / context menu, export/import buttons, Equipment metadata tab.
