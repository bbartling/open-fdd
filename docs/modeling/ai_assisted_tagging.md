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

The **canonical prompt** lives in a single file: **`config/canonical_llm_prompt.txt`** (see [README](https://github.com/bbartling/open-fdd#ai-assisted-data-modeling)). The backend loads it when present (fallback: built-in prompt in code); you can edit the file at any time. The prompt is generic and works for **any site**: single building, campus, or tenant. The only input that changes is the export JSON (from GET /data-model/export, optionally with `?site_id=YourSiteName`). The LLM must preserve all fields, add brick_type, rule_input, **unit** (when known), and polling, and use equipment by name and site_id from the export. The same file can be used as **model context** (e.g. in `pdf/open-fdd-docs.txt` or when building custom doc bundles for an LLM).

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

## In-house AI agent (OpenAI API Assist)

**Where it runs:** In the frontend, open **Data Model Setup** → **Export (for AI / copy-paste)** → click **OpenAI API Assist**. The agent is **optional**; the manual export → external LLM → import flow is always available without it.

**How it’s invoked:** When you click **Tag with OpenAI**, the frontend sends **POST /data-model/tag-with-openai** with your API key, optional chat prompt (HVAC description), model choice, and optional auto-import flag. The backend runs the agent (see below) and returns tagged JSON plus an **agent log**; the UI shows the log and pre-fills the Import textarea.

**What the agent does:** It uses the **same API as the manual process**: server-side **GET /data-model/export** (with optional site filter), then a single LLM call (or chunked calls for large payloads) with the **canonical prompt** from `config/canonical_llm_prompt.txt` (or built-in fallback). The response is validated with the same **DataModelImportBody** Pydantic model as **PUT /data-model/import**. If you enable auto-import, the backend then calls the import logic so the data model is updated in one step. The engineer can still validate on the **Data Model Testing** page (SPARQL / “Summarize your HVAC”) and treat the result as pass or fail.

---

### How the agent works: retry and prompt chaining

The agent is **not** a long-lived process; it runs inside a single **POST /data-model/tag-with-openai** request:

1. **Export** — The backend builds the same export as GET /data-model/export (optionally filtered by site).
2. **System prompt** — Loaded from **`config/canonical_llm_prompt.txt`** when the file exists (otherwise a built-in prompt in code). Edit the file to change behavior; no app restart needed for the next request.
3. **User message** — The export JSON is sent as the user message. If you filled the **chat prompt** in the UI (e.g. “Describe HVAC system and feeds or fed by relationships for AI to tag”), that text is prepended so the LLM can use your description for Brick types and equipment relationships.
4. **LLM call** — One request to OpenAI (or, for very large exports, the backend may split into chunks of 120 rows and merge results) with `response_format={"type": "json_object"}`.
5. **Validation** — The response is parsed as JSON and validated with **DataModelImportBody** (same schema as import). If validation fails:
   - **Prompt chaining:** The error text (e.g. “OpenAI response failed schema validation: …”) is appended to the **next** attempt’s user message, so the model sees what went wrong and is asked to fix it.
   - **Retry** — The backend retries up to a configurable number of attempts (default 3; see `open_fdd/platform/llm_tagger.py` constants). Each attempt is a new LLM call with the same export and, from the second attempt onward, the previous validation error in the prompt.
6. **Agent log** — Each attempt and outcome (attempt, validation_failed, success) is recorded and returned in the response **meta.agent_log**; the UI shows this so you can see retries and that the agent produced valid import JSON.
7. **Optional import** — If you set **Auto-import tagged JSON** in the UI, the backend runs the same import logic as PUT /data-model/import and returns the import result in the response.

So the agent uses **rule-based retry** with **prompt chaining**: same export and rules each time, but after a validation failure the next prompt includes the error so the LLM can correct the output. Constants (max retries, chunk size) live in **`open_fdd/platform/llm_tagger.py`**; the API request can override `max_retries` (1–10).

**Optional dependency:** The `openai` package is required only for this endpoint. If it is not installed, the API returns 500 with a message to install it; the rest of the platform (including manual export/import) works without it.

---

## Automated tagging via the API (summary)

1. Open the **Data Model Setup** page in the frontend.
2. Expand **OpenAI API Assist** (under Export). Optionally edit the **chat prompt** (default: “Describe HVAC system and feeds or fed by relationships for AI to tag”).
3. Enter your OpenAI API key and select a model; optionally check **Tag selected site only** and **Auto-import tagged JSON**.
4. Click **Tag with OpenAI** — the platform calls **POST /data-model/tag-with-openai**, which runs the in-house agent (export → LLM with retry and prompt chaining → validate → optional import). The response includes **meta.agent_log**; the UI shows the log and pre-fills the Import textarea.
5. Review the tagged JSON (and agent log). If you did not auto-import, click **Import** when ready. Use the **Data Model Testing** page to validate (SPARQL / Summarize your HVAC) and pass or fail the result.

**Key handling:** Your API key is sent in the request body over HTTPS and is used only for that request. It is never stored on the server. You can optionally enable *Remember key in this browser* in the UI (saved in `localStorage`) — only on a private, trusted device.

**Users without an API key:** The manual copy-paste workflow (Export → external LLM → Import) remains fully supported.
- [Appendix: API Reference](../appendix/api_reference) — Data model export/import, CRUD
- [BACnet overview](../bacnet/overview) — Discovery and data-model scrape
- [Fault rules](../rules/overview) — Brick-driven rules in `stack/rules/`
