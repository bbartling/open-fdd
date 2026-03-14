---
title: AI-assisted data modeling
parent: Data modeling
nav_order: 4
---

# AI-assisted Brick tagging

Open-FDD supports **AI-assisted data modeling**: use **GET /data-model/export** to dump BACnet discovery and existing points as JSON, then have an **LLM or human** add Brick types, rule inputs, equipment relationships, and which points to poll — and send the result to **PUT /data-model/import**. The platform stays the single source of truth; tagging is the step where raw BACnet objects become a curated, rule-ready dataset.

This workflow is intended for **mechanical engineers and building operators** who need the data model tagged so that FDD rules in `stack/rules/` have the correct inputs and only the right points are logged long-term.

---

## Workflow (export → tag → import)

1. **Discover** — Use the API: **POST /bacnet/whois_range**, then **POST /bacnet/point_discovery_to_graph** per device. The in-memory graph and `config/data_model.ttl` now contain BACnet devices and objects.

2. **Sites and equipment** — Create the building/site and equipment (AHUs, VAVs, zones) via **POST /sites** and **POST /equipment**. Note the returned `site_id` and `equipment_id` UUIDs; the import body requires real UUIDs from the API.

3. **Export** — **GET /data-model/export** (or `?bacnet_only=true` for discovery-only). Returns a single JSON array: BACnet discovery rows plus all DB points. Unimported BACnet rows have `point_id: null`, `polling: false`, and null `site_id`/`equipment_id`/`brick_type`/`rule_input`.

4. **Tag** — Send the export JSON to an LLM or edit manually. For each point set:
   - **site_id**, **external_id** (time-series key)
   - **brick_type** (e.g. `Supply_Air_Temperature_Sensor`, `Zone_Air_Temperature_Sensor`)
   - **rule_input** (name FDD rules use)
   - **unit** when known (e.g. `degF`, `%`, `cfm`, `0/1` for binary). Units are stored in the data model and TTL; the frontend uses them for Plots axis labels and grouping (e.g. temperatures on one axis, humidity on another). Use standard abbreviations so Plots and exports stay consistent.
   - **equipment_id** (optional)
   - **polling: true** for every point that must be **logged long-term** for this job (sensors/setpoints that FDD rules use); **polling: false** for points not needed. The LLM should tell the operator which points will be logged so they can confirm rules in `stack/rules/` have the required inputs.
   - For **equipment relationships** (Brick feeds/isFedBy), use the import **equipment** array: each item has `equipment_id`, optional `feeds_equipment_id` and `fed_by_equipment_id` (UUIDs from GET /equipment).

5. **Import** — **PUT /data-model/import** with body: **points** (array) and optional **equipment** (array for feeds/fed_by only). The API accepts **only** these two keys — no `sites`, `equipments`, or `relationships`. The backend creates/updates points and equipment relationships, then rebuilds the RDF and TTL.

6. **Scraping** — The BACnet scraper (data-model path) loads points where `bacnet_device_id`, `object_identifier`, and **polling = true**; it calls diy-bacnet-server **client_read_multiple** per device and writes to `timeseries_readings`. Grafana and FDD use the same data model.

---

## API contract (import)

- **points** (required): Each row is a point to **create** (omit `point_id`; set `site_id`, `external_id`, `bacnet_device_id`, `object_identifier`) or **update** (set `point_id` and fields to change). **site_id** and **equipment_id** must be real UUIDs from GET /sites and GET /equipment.
- **equipment** (optional): Updates existing equipment with Brick feeds/isFedBy. Each item: `{ "equipment_id": "<uuid>", "feeds_equipment_id": "<uuid> | null", "fed_by_equipment_id": "<uuid> | null" }`.

**diy-bacnet ready:** The list of points to poll is **GET /data-model/export** filtered to rows where **polling === true**; each has `bacnet_device_id` and `object_identifier`.

---

## LLM prompt and agent guidelines

The prompt in the [README](https://github.com/bbartling/open-fdd#ai-assisted-data-modeling) is **generic** and works for **any site**: single building, campus, or tenant. The only input that changes is the export JSON (from GET /data-model/export, optionally with `?site_id=YourSiteName`). The LLM must preserve all fields, add brick_type, rule_input, **unit** (when known), and polling, and use equipment by name and site_id from the export.

For exact schema details and import body (points + equipment only), see the [Technical reference](../appendix/technical_reference). It defines the primary task (Brick tagging), the export → tag → import flow, polling semantics, equipment feeds, and the **unit** field (e.g. degrees-fahrenheit, percent) used by the frontend and stored in the RDF/TTL.

---

## Rules for this project (what to send the LLM)

To have the LLM align **rule_input** and Brick types with your FDD rules, you can include:

- **[Fault rules overview](../rules/overview)** — FDD rule types and YAML format.
- **[Expression Rule Cookbook](../rules/expression_rule_cookbook)** — AHU, chiller, weather, and advanced recipes; **rule_input** examples (e.g. sat, rat, zone_temp, sf_status).
- Your project’s **YAML rule files** (e.g. from `stack/rules/`) — Paste snippets so the LLM uses the same input names.

See [LLM workflow (export + rules + validate → import)](llm_workflow) for the full one-shot flow and validating LLM output so it parses on the backend.

---

## See also

- [LLM workflow](llm_workflow) — One prompt + export JSON + optional rules; validate with schema/Pydantic; then import and run FDD/tests.
- [Data model overview](overview) — Flow (DB → TTL → FDD)

---

## Automated tagging via the API

If you have an OpenAI API key, you can skip the copy-paste step entirely:

1. Open the **Data Model** page in the frontend.
2. In the **AI Tagging** card (between Export and Import), enter your OpenAI API key and select a model.
3. Click **Tag with AI** — the platform calls `POST /data-model/tag-with-openai`, which:
   - Runs `GET /data-model/export` server-side (respecting the site filter from the top bar).
   - Sends the canonical prompt + export JSON to OpenAI.
   - Validates the response against the import schema.
   - Returns the tagged JSON, pre-filling the Import textarea below.
4. Review the tagged JSON, then click **Import**.

**Key handling:** Your API key is sent in the request body over HTTPS and is used only for the duration of that request. It is never stored on the server. You can optionally enable *Remember key in this browser* in the UI, which saves the key in `localStorage` — only enable this on a private, trusted device.

**Users without an API key:** The manual copy-paste workflow described in the Workflow section above remains fully supported and is always available.
- [Appendix: API Reference](../appendix/api_reference) — Data model export/import, CRUD
- [BACnet overview](../bacnet/overview) — Discovery and data-model scrape
- [Fault rules](../rules/overview) — Brick-driven rules in `stack/rules/`
