---
title: AI-assisted data modeling
parent: Data modeling
nav_order: 4
---

# AI-assisted Brick tagging

Open-FDD supports **AI-assisted data modeling**: use **GET /data-model/export** to dump BACnet discovery and existing points as JSON, then have an **LLM or human** add **Brick point classes** (`brick_type`), **Brick equipment classes** (`equipment_type` — best guess the operator confirms), rule inputs, equipment relationships, and which points to poll — and send the result to **PUT /data-model/import**. The platform stays the single source of truth; tagging is the step where raw BACnet objects become a curated, rule-ready dataset.

This workflow is intended for **mechanical engineers and building operators** who need the data model tagged so that FDD rules in `stack/rules/` have the correct inputs and only the right points are logged long-term.

---

## Workflow (export → tag → import)

1. **Discover** — Use the API: **POST /bacnet/whois_range**, then **POST /bacnet/point_discovery_to_graph** per device. The in-memory graph and `config/data_model.ttl` now contain BACnet devices and objects.

2. **Sites and equipment** — Create the building/site and equipment (AHUs, VAVs, zones) via **POST /sites** and **POST /equipment**. Keep `site_id` UUIDs from export when present. For equipment assignment on import, you can use `equipment_id` UUIDs or `equipment_name` (resolved/created under `site_id`).

3. **Export** — **GET /data-model/export** (or `?bacnet_only=true` for discovery-only). Returns a single JSON array: BACnet discovery rows plus all DB points. Unimported BACnet rows have `point_id: null`, `polling: false`, and null `equipment_id`/`brick_type`/`rule_input`. **`site_id` / `site_name` are pre-filled** when you pass **`?site_id=`** (UUID or site name), when the **Data model** UI has a site selected in the top bar, or when the database has **exactly one site** — so LLMs can assign `equipment_name` safely. With **multiple sites** and no `site_id` filter, those fields stay null until you scope the export.

4. **Tag** — Send the export JSON to an LLM or edit manually. For each point set:
   - **site_id**, **external_id** (time-series key)
   - **brick_type** (e.g. `Supply_Air_Temperature_Sensor`, `Zone_Air_Temperature_Sensor`) — Brick **point** class
   - **equipment_type** (e.g. `Air_Handling_Unit`, `Variable_Air_Volume_Box`) — Brick **1.4 equipment** class local name when you set **equipment_name**, so **Data Model Testing** preset buttons (AHUs, VAVs, chillers, …) return meaningful counts after import. Use the **best defensible guess**; the operator corrects rare mistakes with one-click SPARQL checks. See [LLM workflow](llm_workflow) canonical prompt and `frontend/src/data/brick-1.4-query-class-allowlist.ts`.
   - **rule_input** (name FDD rules use)
   - **unit** when known (e.g. `degF`, `%`, `cfm`, `0/1` for binary). Units are stored in the data model and TTL; the frontend uses them for Plots axis labels and grouping (e.g. temperatures on one axis, humidity on another). Use standard abbreviations so Plots and exports stay consistent.
   - **equipment_id** (optional) or **equipment_name** (optional, with site_id)
   - **polling: true** for every point that must be **logged long-term** for this job (sensors/setpoints that FDD rules use); **polling: false** for points not needed. The LLM should tell the operator which points will be logged so they can confirm rules in `stack/rules/` have the required inputs.
   - For **equipment relationships** (Brick feeds/isFedBy), optional **engineering**, and **equipment_type** on named equipment, use the import **equipment** array. UUID-based and name-based forms are both supported; name-based relationship rows require `site_id`.

5. **Import** — **PUT /data-model/import** with body: **points** (array) and optional **equipment** (array for feeds/fed_by, **equipment_type**, **engineering**, etc.). The API accepts **only** these two keys — no `sites`, `equipments`, or `relationships`. The backend creates/updates points and equipment relationships, then rebuilds the RDF and TTL.

6. **Scraping** — The BACnet scraper (data-model path) loads points where `bacnet_device_id`, `object_identifier`, and **polling = true**; it calls diy-bacnet-server **client_read_multiple** per device and writes to `timeseries_readings`. Grafana and FDD use the same data model.

---

## API contract (import)

- **points** (required): Each row is a point to **create** (omit `point_id`; set `site_id`, `external_id`, `bacnet_device_id`, `object_identifier`) or **update** (set `point_id` and fields to change). `site_id` should remain the export UUID when present. `equipment_id` is optional if `equipment_name` is provided with `site_id`.
- **equipment** (optional): Updates equipment with Brick feeds/isFedBy, **`equipment_type`** (Brick class for `rdf:type`), **`engineering`**, **`metadata`**. Rows may use UUID fields (`equipment_id`, `feeds_equipment_id`, `fed_by_equipment_id`) or name fields (`equipment_name`, `feeds`, `fed_by`) with `site_id` for resolution.

**diy-bacnet ready:** The list of points to poll is **GET /data-model/export** filtered to rows where **polling === true**; each has `bacnet_device_id` and `object_identifier`.

---

## LLM prompt and agent guidelines

**Where this is documented:** the tagging rules and agent flow are described **on this page** (you are in the right place) and summarized under **[LLM tagging workflow](../appendix/technical_reference#llm-tagging-workflow)** in the Technical reference. The [README](https://github.com/bbartling/open-fdd#ai-and-data-modeling) points here under **AI and data modeling**.

**Canonical prompt text:** The **full** copy-paste system prompt (points + equipment rules, strict JSON output, **fault-first pre-flight** for polling) is on the docs site under **[LLM workflow — Copy/paste prompt template](llm_workflow#copy-paste-prompt-template-recommended)**. Published hub: **[Data modeling](https://bbartling.github.io/open-fdd/modeling/)** (same content as the repo after Pages build). You can save the same text to a local file (e.g. `pdf/canonical_llm_prompt.txt`) for agents; keep it in sync when you change instructions. The running API does **not** auto-inject this into chat UIs; load it yourself or point agents at the published section. For **HTTP model context**, use **`GET /model-context/docs`**, which serves **`pdf/open-fdd-docs.txt`** (or **`OFDD_DOCS_PATH`**)—regenerate that bundle after doc changes so agents see updates. Agents that can **fetch the web** may also load the [modeling hub](https://bbartling.github.io/open-fdd/modeling/) or the [template anchor](https://bbartling.github.io/open-fdd/modeling/llm_workflow#copy-paste-prompt-template-recommended) directly.

**What the prompt must cover:** It should be generic for **any site** (single building, campus, or tenant). The only input that changes per run is the export JSON from **GET /data-model/export** (optionally `?site_id=YourSiteName`). The LLM must preserve all fields, add **brick_type**, **rule_input**, **unit** (when known), and **polling**, and use equipment by name and **site_id** from the export. **Best practice:** the operator should state **which faults/rules** will run and supply **YAML (or snippets) where possible** before treating **polling** as final; the canonical prompt enforces that as **pre-flight / job context** or a **conservative draft**.

For exact schema details and import body (points + equipment only), see the [Technical reference](../appendix/technical_reference). It defines the primary task (Brick tagging), the export → tag → import flow, polling semantics, equipment feeds, and the **unit** field (e.g. degrees-fahrenheit, percent) used by the frontend and stored in the RDF/TTL.

---

## Rules for this project (what to send the LLM)

**Start here for real jobs:** which Open-FDD faults you will run, plus **actual YAML** for those rules when you have it — that yields the best **polling** and **rule_input** choices.

To have the LLM align **rule_input**, Brick types, **units**, and **polling** with your FDD rules, include:

- **[Fault rules overview](../rules/overview)** — FDD rule types and YAML format.
- **[Expression Rule Cookbook](../expression_rule_cookbook)** — AHU, chiller, weather, and advanced recipes; **rule_input** examples (e.g. sat, rat, zone_temp, sf_status).
- Your project’s **YAML rule files** (e.g. from `stack/rules/`) — Paste snippets so the LLM uses the same input names.

See [LLM workflow (export + rules + validate → import)](llm_workflow) for the full one-shot flow and validating LLM output so it parses on the backend.

---

## See also

- [LLM workflow](llm_workflow) — One prompt + export JSON + optional rules; validate with schema/Pydantic; then import and run FDD/tests.
- [Data model overview](overview) — Flow (DB → TTL → FDD)

---

## External agent integration (Open‑Claw or any OpenAI-compatible LLM)

**Where it runs:** Outside Open‑FDD (in your external LLM/Open‑Claw environment). Open‑FDD stays the single source of truth; your agent orchestrates `GET /data-model/export` → LLM tagging → `PUT /data-model/import`.

**How it’s invoked:** Your external agent calls `GET /data-model/export` (optionally with a site filter), tags the export via Open‑Claw (OpenAI-compatible) using the canonical prompt, then imports validated JSON with `PUT /data-model/import`. If validation fails, include the error text and retry (prompt chaining).

**What the agent does:** It uses the same API endpoints as the manual process: `GET /data-model/export` (optionally filtered by site) → LLM tagging using the canonical prompt → validate that the returned JSON matches Open‑FDD’s import schema → `PUT /data-model/import` (or return JSON for the engineer to import).

---

### External retry loop (prompt chaining)

The agent is typically **not** a long-lived process; your external loop exports the model, tags it, validates the output, and retries when needed:

1. **Export** — Call `GET /data-model/export` (optionally filtered by site) and send the export JSON to your agent.
2. **System prompt** — Use the full tagging instructions (this page + Technical reference, or your local `pdf/canonical_llm_prompt.txt` if you maintain one) as the Open‑Claw/OpenAI-compatible **system** prompt.
3. **User message** — Send the export JSON as the user message. Optionally prepend any engineer description of feeds/fed_by topology and assumptions so the LLM can choose correct Brick types and relationships.
4. **LLM call** — Call your Open‑Claw/OpenAI-compatible LLM once (for typical payloads). For very large exports, your agent may split into chunks and merge results. Request JSON output (for example with `response_format={"type": "json_object"}`).
5. **Validation** — The response is parsed as JSON and validated with **DataModelImportBody** (same schema as import). If validation fails:
   - **Prompt chaining:** When validation fails, append the error text to the next attempt so the model can correct the JSON.
   - **Retry** — Retry up to a configurable max attempts in your agent.
6. **Agent log** — Optionally log attempts/outcomes so the engineer can inspect what changed between retries.
7. **Optional import** — Either return JSON for review, or immediately call `PUT /data-model/import` after validation.

So the agent uses **retry** with **prompt chaining**: keep the same export/rules, and after a validation failure include the error so the LLM can correct its output.

---

## Automating tagging (external agents)

1. Call `GET /data-model/export` to get the export JSON (optionally with `?site_id=...`).
2. Fetch Open‑FDD documentation context for the LLM: `GET /model-context/docs` (use `query=...` to retrieve relevant sections).
3. Prompt/tag with Open‑Claw (OpenAI-compatible) to produce import JSON that matches the Open‑FDD schema.
4. Validate and import:
   - either return JSON for the engineer to review, or
   - call `PUT /data-model/import` with the validated JSON.

---

## Troubleshooting import failures (fixing your tagged JSON)

Sometimes the LLM returns valid JSON that passes schema validation, but `PUT /data-model/import` still rejects it during referential checks.

### `site_id` must be a UUID

If the UI shows an error like:
`site_id must be a valid UUID ... Got: 'BensOffice'`
it means a **UUID field** holds a human-readable value (often the site name was pasted into `points[].site_id`).

Human fix (pick the path that matches your row shape):

1. **Preferred:** Replace the bad value with the **real site UUID** from `GET /data-model/export` or `GET /sites` (same site the row belongs to). This is always safe for **updates** (`point_id` set) and for **creates**, and it keeps **name-based** `equipment[]` rows valid — those rows still **require** a proper `site_id` UUID alongside `equipment_name` / `feeds` / `fed_by`.
2. **Creates only (`point_id` omitted):** If the backend should resolve the site by name, you may set `site_id` to `null` (or remove the key) **and** set `site_name` to an existing site name (see import logic in the API). Do **not** use this as a blanket fix for every row: any row that uses **equipment by name** must keep a valid `site_id` UUID.
3. **Bad equipment or point UUIDs:** If the error is about `point_id` or `equipment_id`, remove or replace only those fields with IDs from your DB/export — don’t strip `site_id` from unrelated rows.

If `PUT /data-model/import` rejects otherwise-valid JSON, re-run tagging with prompt chaining:
include the import error text in your next LLM attempt so it can correct UUIDs/references, or return the JSON for a human to edit and import manually.

---

## Possible extension: AI assist on Data Model Testing

A future **Data Model Testing** page could offer a second AI assist (same chat style as on Data Model Protocols): the engineer describes what they see (e.g. SPARQL summary, missing relationships, or test failure), and the model suggests **changes as import JSON** (points/equipment) so the engineer can apply and re-test. Under the hood this would use a **separate prompt** from the tagging prompt:

- **Input:** Current data model context (e.g. TTL snippet or SPARQL “Summarize your HVAC” result) plus the engineer’s message (e.g. “Add feeds/fed-by between AHU-1 and VAV-1”, “Fix the brick_type for SA-T”).
- **Output:** Same schema as the tagging flow — valid **points** and **equipment** import JSON only — so the same **PUT /data-model/import** and validation path apply. The engineer reviews, applies, then re-runs SPARQL or predefined tests and passes/fails.

That way: **Setup** = tag from export (same instructions as above, optionally stored in `pdf/canonical_llm_prompt.txt`); **Testing** = revise from current model + chat (optional second file e.g. `pdf/canonical_llm_prompt_testing.txt`). Both use the same API and retry/prompt-chaining behavior; only the system prompt and user message differ.

---

- [Appendix: API Reference](../appendix/api_reference) — Data model export/import, CRUD
- [BACnet overview](../bacnet/overview) — Discovery and data-model scrape
- [Fault rules](../rules/overview) — Brick-driven rules in `stack/rules/`
