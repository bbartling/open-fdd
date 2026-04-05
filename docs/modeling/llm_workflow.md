---
title: LLM workflow (export + rules + validate → import)
parent: Data modeling
nav_order: 5
---

# LLM workflow: one prompt, export JSON, rules, and validated import

This page describes a **single upload** workflow for mechanical engineers: send the **canonical prompt**, the **data-model export JSON**, and **fault/rule context** (strongly recommended) to an LLM; get back import-ready JSON; **validate** it so you know it will parse on the Open-FDD backend; then **PUT /data-model/import** and run FDD (or Sparkl/tests) as needed.

**Best practice:** Decide **which Open-FDD faults and rules** you will run *before* finalizing `polling`. The canonical prompt is **fault-first**: it tells the model to gather job context (faults, YAML, units, production vs bench, weather scope) or to stay conservative on polling until that context exists.

> **Automated path available:** External OpenAI-compatible agents (for example Open‑Claw) can automate the same flow by calling `GET /data-model/export`, fetching platform documentation context from `GET /model-context/docs`, and then calling `PUT /data-model/import` with validated import JSON. The manual copy-paste workflow below always works too.

> **Web-connected agents:** If your LLM can fetch HTTPS documentation, point it at the published **[Data modeling](https://bbartling.github.io/open-fdd/modeling/)** hub and this page’s template anchor **[Copy/paste prompt template (recommended)](https://bbartling.github.io/open-fdd/modeling/llm_workflow#copy-paste-prompt-template-recommended)** in addition to (or alongside) `GET /model-context/docs`, so instructions stay aligned with the live docs site.

> **Full AFDD stack vs column-map resolvers:** This workflow still targets **Brick** point classes (`brick_type`), **`rule_input`**, and related import fields because **rule YAML** on the platform uses **Brick-class logical names**. In **`fdd-loop`**, the default **`BrickTtlColumnMapResolver`** builds **`column_map`** from **`config/data_model.ttl`** (same semantic model you enrich with import JSON). The LLM does **not** emit a separate “ontology manifest” for PyPI-style **`ManifestColumnMapResolver`**—that path is for **library / custom** pipelines ([Engine-only deployment and external IoT pipelines](../howto/engine_only_iot), [column map resolver workshop](../../examples/column_map_resolver_workshop/README.md)). If you ever run the loop with a **manifest-only** resolver, keep **rule YAML** and **`brick_type`** aligned with whatever logical keys your rules use.

---

## What you upload to the LLM

1. **The canonical prompt** — Use **[AI-assisted data modeling](ai_assisted_tagging)** (section *LLM prompt and agent guidelines*), the inline template **below** on this page (“Copy/paste prompt template”), or the [Technical reference — LLM tagging workflow](../appendix/technical_reference#llm-tagging-workflow). You can copy from this page or keep an optional local mirror (e.g. `pdf/canonical_llm_prompt.txt`) for agents. The prompt must tell the LLM to return only `{"points": [...], "equipment": [...]}` with Brick types, rule_input slugs, equipment_name, feeds/fed_by, polling, and units (subject to the **pre-flight / job context** rules in the template).

2. **The export JSON** — From **GET /data-model/export** (optionally `?site_id=YourSiteName`). Each row includes point fields (`point_id`, `bacnet_device_id`, `object_identifier`, `object_name`, `external_id`, `site_id`, `site_name`, `equipment_id`, `equipment_name`, `brick_type`, `rule_input`, `unit`, `polling`, …). Rows may also include **`engineering`** (and **`equipment_metadata`**) — a **per-equipment** mirror from the DB so the LLM sees rated/submittal context next to points. On **import**, write engineering updates under **`equipment[].engineering`**, not as ad-hoc point fields (see [Data model engineering](../howto/data_model_engineering) and `examples/223P_engineering/`). Unimported BACnet rows have `point_id: null` and null tagging fields until you import.

3. **Faults and rules for this job (strongly recommended)** — So the LLM can align **rule_input**, **Brick types**, **units**, and especially **polling** with what you will actually run in Open-FDD:
   - Paste **YAML** from your project’s rules (e.g. from `stack/rules/` or your own rule files). **This is the best input for correct polling decisions** — the model can see exactly which point inputs each rule uses.
   - Or point the LLM at the **[Fault rules overview](../rules/overview)** and **[Expression Rule Cookbook](../expression_rule_cookbook)** (AHU, chiller, weather, advanced recipes) and list which fault IDs or recipes apply.

> **Polling and YAML:** Without fault/rule context, many BACnet points may be tagged correctly but should still stay `polling: false`. The canonical prompt defaults to **asking for job context first** or emitting a **conservative draft** (mostly `polling: false`) until you provide which faults run and ideally the **actual rule YAML** for the job.

---

## Copy/paste prompt template (recommended) {#copy-paste-prompt-template-recommended}

Use this as your LLM **system** or **developer** prompt when transforming `GET /data-model/export` into import JSON. This is the **canonical** copy-paste text for the published docs (save to a local file such as `pdf/canonical_llm_prompt.txt` if you want a path for agents or runbooks).

```text
You are transforming Open-FDD export JSON into Open-FDD import JSON.

I will paste JSON from:
GET /data-model/export?site_id=<site_id>

Your job is to return ONLY valid JSON with EXACTLY these two top-level keys:

{
  "points": [...],
  "equipment": [...]
}

Do not return markdown.
Do not return explanations.
Do not return comments.
Do not return any extra top-level keys.

Exception for multi-turn chat: if fault/rule job context is still missing and you must ask pre-flight questions first, you may reply with plain-language questions only in that turn (see PRE-FLIGHT below). When you emit import JSON, the STRICT OUTPUT REQUIREMENTS at the end apply.

--------------------------------------------------
PRE-FLIGHT / JOB CONTEXT (required before final polling decisions)
--------------------------------------------------

Polling must be driven by the **actual faults and rules** the operator plans to run in Open-FDD — not by “this point looks generally useful.”

Before deciding final polling values, establish job context.

**Required pre-flight question:** What faults/rules are you going to run in Open-FDD?

Ask or confirm the following (plain language) if not already answered:

2. Can you provide the actual YAML rule files or rule snippets for this job?
3. Are units imperial or metric for this job?
4. Is this a production/live HVAC job or a bench/demo/test bench?
5. Do you want weather-related rules or weather polling included?
6. Should polling be limited to points required by the selected faults, or also include extra plotting/trending points the operator explicitly wants?

HARD RULE — if faults/rules context is missing:

- Either (a) ask the pre-flight questions above and wait (no import JSON in that turn), OR (b) return import JSON that is an explicitly **conservative draft**: set polling=false for every point unless it is clearly essential; do **not** enable broad polling coverage by guesswork.
- Do not treat aggressive polling=true choices as “final” until the operator has described which faults run and (ideally) supplied YAML or clear rule snippets.

If YAML rules or snippets **are** provided:

- Align brick_type, rule_input, unit, and polling with those rules’ inputs.
- Set polling=true primarily for points **required** by the selected faults, plus any points the operator **explicitly** approved for plotting/trending.
- Do not turn on polling for unrelated “nice to have” points unless the operator asked for broader trending.

**After faults/rules are known, you must:**

- Infer which **Brick classes** and **rule_input** slugs those rules require (from YAML expressions and the Expression Rule Cookbook when YAML is thin). On the full Open-FDD stack, the engine maps those Brick names to trend/BACnet columns from the published data model (TTL), so keep **brick_type** and **rule_input** consistent with the YAML—not a separate hand-authored column_map in this JSON.
- Set **polling=true** for points that clearly supply those required inputs once tagged.
- Leave **polling=false** for unrelated points unless the operator explicitly asked for broader trending/plotting.

**Example:** If the operator runs only **sensor-bounds** and **sensor-flatline**-style temperature rules, BACnet **commands**, **setpoints**, **occupancy/schedules**, and **unrelated weather/Open-Meteo** points usually stay **polling=false** unless the operator asked to trend them or a named rule truly needs them.

--------------------------------------------------
POINT RULES
--------------------------------------------------

For each point in the input:

1. KEEP every existing field exactly as provided, including:
- point_id
- bacnet_device_id
- object_identifier
- object_name
- external_id
- site_id
- site_name
- equipment_id
- any other existing point fields present in the export

Note: the export may include **engineering** / **equipment_metadata** on each row (a mirror of **equipment**-level metadata). For **PUT /data-model/import**, rated/submittal engineering belongs under **equipment[].engineering** (see EQUIPMENT RULES). Do not add spurious extra keys on point objects if your validator rejects them; fold engineering into the **equipment** array once per **equipment_name** + **site_id**.

2. ADD or FILL these fields:
- brick_type (Brick **point** class — sensor, command, setpoint, …)
- rule_input
- polling
- unit
- equipment_name
- equipment_type (Brick **equipment** class — see §4 — powers Data Model Testing summary buttons)

3. brick_type:
Choose the best matching Brick class for the point.
Use a standard Brick class name such as:
- Supply_Air_Temperature_Sensor
- Return_Air_Temperature_Sensor
- Mixed_Air_Temperature_Sensor
- Zone_Air_Temperature_Sensor
- Damper_Position_Command
- Supply_Air_Flow_Sensor
- Static_Pressure_Sensor
- Occupancy_Command
Prefix with "brick:" only if the input already uses that style consistently. Otherwise omit the prefix.

4. equipment assignment:
Assign points to equipment by NAME ONLY.
Example:
- "equipment_name": "AHU-1"
- "equipment_name": "VAV-1"

Do NOT use equipment_id or any UUID for equipment relationships.

**Conservative equipment_name inference:**
- Set or change **equipment_name** only when **strongly supported** by BACnet **device** grouping, consistent **object_name** / **external_id** patterns, and any operator brief — not from a single ambiguous point name.
- If grouping is unclear, keep the export’s **equipment_name** / **equipment_id** relationship as-is rather than inventing AHUs/VAVs.

**equipment_type (Brick 1.4 equipment class — best LLM guess, human verifies with one click):**
- When you set **equipment_name** on points (or list equipment in **equipment[]**), also set **equipment_type** to the **most specific defensible Brick equipment class** as a **bare local name** (no `brick:` prefix), matching what Open-FDD writes to RDF for `rdf:type`.
- Goal: the operator can open **Data Model Testing → Summarize your HVAC** and use preset buttons (**AHUs**, **VAV boxes**, **Chillers**, **Central plant**, **Meters**, …) without re-tagging. Those queries filter on Brick **1.4** classes such as:
  - **Air_Handling_Unit** — central air handler (supply/return/mixed air, fan, coils context)
  - **Variable_Air_Volume_Box** or **Variable_Air_Volume_Box_With_Reheat** — VAV / fan-powered terminal
  - **Chiller**, **Boiler**, **Cooling_Tower**, **Water_Pump**, **Heat_Exchanger**
  - **Chilled_Water_System**, **Condenser_Water_System**, **Hot_Water_System** — distribution systems when the row truly represents that system
  - **HVAC_Zone** — thermal / zoning context when points are zone-level only
  - **Building_Electrical_Meter** — building-level electrical meter equipment (not every kW sensor)
  - Generic fallback: **Equipment** (Open-FDD default) when class is unclear — better than mis-typing a VAV as a Chiller.
- **Same names as the UI presets** are maintained in the frontend allowlist **`brick-1.4-query-class-allowlist.ts`** (regression test: **`data-model-testing-queries.brick.test.ts`**).
- On **equipment[]** rows, include **equipment_type** whenever you include **equipment_name** + **site_id** so created/updated equipment gets the correct type before points attach.

5. unit:
Fill unit when known.
Use standard abbreviations consistent with the job units mode from pre-flight (imperial vs metric):
- temperature -> "degF" or "°F" (imperial) / "degC" or "°C" (metric) as appropriate
- percentage -> "percent" or "%"
- airflow -> "cfm" (imperial) or align with metric job conventions when stated
- binary / boolean -> "0/1"
- power -> "W"
- irradiance -> "W/m²"
Preserve unit strings already present in the export when they are consistent with the stated job mode; do not rewrite known-good values unless the operator asked for conversion.
If unknown, use null.

**Conservative units (power, flow, energy):**
- Do **not** force **unit** for ambiguous power, flow, or energy points (e.g. kW vs W, CFM vs percent of max, BTU vs MBH) without **operator confirmation** or an unambiguous BACnet engineering unit in context.
- Prefer **null** over a confident-looking guess that could mislead FDD and plots.

6. polling:
Set polling=true **primarily** for points required by the **specific faults/rules** the operator intends to run, plus any **operator-approved** plotting/trending points (see pre-flight question 6).
Set polling=false for points not needed by those rules or approved use cases.
Do **not** enable broad polling just because a point looks generally useful.
If fault/rule context has not been provided, follow the HARD RULE in PRE-FLIGHT (conservative draft or ask first).
If YAML or rule snippets were provided, align polling (and brick_type, rule_input, unit) with those rules.

7. rule_input:
Only populate rule_input when it is actually needed for disambiguation or explicit aliasing.

Use rule_input in these cases:
- two or more points in the same equipment or rule scope share the same Brick class
- a rule needs a stable explicit alias that cannot be reliably inferred from Brick class alone
- the point name clearly indicates a meaningful distinction such as pre/post, entering/leaving, heating/cooling, min/max, supply/return when same-class ambiguity exists

Example:
If one AHU has two Supply_Air_Temperature_Sensor points:
- SAT before coil -> rule_input: "sat_pre"
- SAT after coil -> rule_input: "sat_post"

If only one point of that Brick class exists in scope and it is unambiguous, set:
- "rule_input": null

Do NOT invent unnecessary rule_input values for every point.

8. weather / Open-Meteo / network weather points:
Do not invent weather equipment or weather points that are not in the export.
If the export already contains Open-Meteo or other weather/network points, keep those rows in the output. Set polling=true only when weather-related faults/rules are in scope, or the operator explicitly wants weather polling/plotting; otherwise prefer polling=false for weather rows when fault context does not require them.
Do not add new weather points unless the operator or attached rules explicitly require them.

9. fallback behavior:
If uncertain:
- brick_type = null
- rule_input = null
- unit = null
- polling = false
- equipment_type = omit or null (backend defaults to generic Equipment — use this instead of a wrong class)

--------------------------------------------------
REAL-JOB / CONSERVATIVE MODE (not optional for production buildings)
--------------------------------------------------

Bench and demo setups can be forgiving; **on a real live HVAC job** the model must not drift from discoverable truth.

**Do not invent or guess:**

- Extra BACnet devices, synthetic weather stations, or integration “placeholder” equipment
- Equipment rows or feeds/fed_by topology that are not in the export, the user’s brief, or an attached as-built
- Point rows that were not in the export (no hallucinated objects)
- **Engineering** numerics (HP, tons, MBH, design CFM, kW) on **equipment[].engineering** without operator-provided submittal/spec text

**Preserve identity exactly** (character-for-character when the export provides them):

- `bacnet_device_id`, `object_identifier`, `object_name`, `external_id`, `point_id`, `site_id`, `site_name`, `equipment_id`

**When unsure, prefer the safer default:**

- `null` for unknown Brick type or unit — not a best guess
- `polling: false` unless the point is clearly needed for the faults/rules or plotting/trending the operator asked for
- Omit `feeds` / `fed_by` rather than inferring ductwork relationships
- Saying (in a side channel) “cannot determine X from export” is better than fabricating X in JSON

**Demo vs live:** Use pre-flight answers: test-bench convenience must not override the rules above on a production import.

**Operator review before import (short checklist):**

1. Compare row count and key BACnet fields to the latest `GET /data-model/export` — no mystery devices.
2. Confirm every non-null `site_id` is still a UUID from `GET /sites`.
3. `PUT dry-run` is not currently supported by the Open-FDD API for `PUT /data-model/import`; use schema/Pydantic validation first, and if you need a no-risk rehearsal, run the same `PUT` against a staging instance while comparing inputs from `GET /data-model/export` and site UUIDs from `GET /sites`.
4. After import, verify a handful of BACnet reads match the gateway for the same object ids.
5. On **Data Model Testing**, run **AHUs**, **VAV boxes**, **Class summary**, etc., to confirm **equipment_type** choices match reality (quick human QA).

--------------------------------------------------
EQUIPMENT RULES
--------------------------------------------------

Create an "equipment" array with one entry per equipment.

Each equipment item must use this shape:

{
  "equipment_name": "AHU-1",
  "equipment_type": "Air_Handling_Unit",
  "site_id": "<same site_id as the points>",
  "feeds": ["VAV-1"]
}

or

{
  "equipment_name": "VAV-1",
  "equipment_type": "Variable_Air_Volume_Box",
  "site_id": "<same site_id as the points>",
  "fed_by": ["AHU-1"]
}

Rules:
- Use equipment names only
- Do not use equipment UUIDs
- Preserve the exact site_id from the export
- Set **equipment_type** on each row (see §4) so Brick `rdf:type` matches **Data Model Testing** preset queries (Brick **1.4** vocabulary).
- Include feeds/fed_by only when supported by the provided data or clearly specified by the user
- Do not invent mechanical relationships unless they are explicitly given or obvious from the provided context

**Optional — engineering metadata (`equipment[].engineering`):**
- Open-FDD **GET /data-model/export** duplicates **equipment.metadata.engineering** on each point row as **engineering** for LLM context. On import, put updates under **equipment[]** using the same **equipment_name** + **site_id**, with an **engineering** object (nested sections such as **mechanical**, **electrical**, **controls**, **topology**, **documents** — see project examples).
- You **may** help capture **rated** data: design CFM, cooling/heating capacity, fan or pump motor nameplate (HP/kW/FLA), coil or heat-exchanger ratings, feeder/panel references, **when the operator provides submittal, schedule, or as-built values** (or asks you to transcribe pasted specs).
- Do **not** invent numeric ratings (HP, tons, MBH, CFM, kW) from BACnet object names alone.
- Preserve existing **engineering** from the export when present unless the operator asks to correct it.

--------------------------------------------------
STRICT OUTPUT REQUIREMENTS
--------------------------------------------------

When emitting import JSON:
- Return ONLY valid JSON
- EXACTLY two top-level keys: "points" and "equipment"
- No "sites"
- No "relationships"
- No "equipments"
- No prose
- No markdown
- No comments

If duplicate external_id appears for the same site, keep the last occurrence.

Now process the following input JSON:
```

After the final line, paste the **export JSON** (or send it as the next user message). This template works for manual copy-paste and external agents (including Open‑Claw workflows).

**Again, for agents with web access:** [Data modeling (GitHub Pages)](https://bbartling.github.io/open-fdd/modeling/) and [this template section](https://bbartling.github.io/open-fdd/modeling/llm_workflow#copy-paste-prompt-template-recommended).

---

## Where the rules live

| What | Where |
|------|--------|
| **Fault rules overview** | [docs/rules/overview](../rules/overview) — FDD rule types, YAML format, Brick-driven inputs. |
| **Expression Rule Cookbook** | [docs/expression_rule_cookbook](../expression_rule_cookbook) — AHU, chiller, weather, and advanced recipes; **rule_input** examples and expression patterns. |
| **Actual YAML rule files** | `stack/rules/` in the repo (or your `rules_dir`). Paste snippets into the LLM session so it uses the same input names **and** can set polling only where rules need data. |

The cookbook is **not** a fault rule file itself; it’s documentation. The **rules you want to use** are the YAML files in `stack/rules/` (or your project’s rules). For the LLM, prefer pasting that YAML; you can also say “use rule_input slugs from the Expression Rule Cookbook (sat, rat, zone_temp, …)” when YAML is not at hand — but polling decisions will be less certain until you tie them to concrete faults.

---

## Engineering metadata (fan HP, pumps, coils, design CFM, …)

Yes — the **export** exposes equipment-level engineering on each row as **`engineering`** (and raw **`equipment_metadata`**). The **import** accepts the same data on **`equipment[]`** via **`engineering`**, merged into `equipment.metadata.engineering` in PostgreSQL and emitted into the knowledge graph (see **`open_fdd/platform/data_model_ttl.py`**).

Use this for **nameplate / submittal** style fields (design CFM, cooling/heating capacity, motor HP or FLA, feeder panel, topology sketches, source drawing references). **FDD rules still run on time-series columns** from polled points; engineering scalars are for **context**, SPARQL, dashboards, and downstream analytics unless you extend the runner.

- **Docs:** [Data model engineering (Brick + 223P MVP)](../howto/data_model_engineering)
- **Example import:** `examples/223P_engineering/engineering_import_example.json`

The canonical prompt tells the LLM to **only** fill or change engineering when the operator supplies evidence — not to invent tons, HP, or CFM from BACnet names alone.

---

## Feeds / fed_by (HVAC topology)

- **feeds** — This equipment supplies another (e.g. AHU feeds VAV).
- **fed_by** — This equipment is supplied by another (e.g. VAV fed_by AHU).

If topology is not known confidently, omit feeds/fed_by rather than guessing. You can add or refine relationships later.

---

## Validate before import (so backend CRUD accepts it)

The Open-FDD **PUT /data-model/import** endpoint expects a body that matches the **DataModelImportBody** Pydantic model: exactly `points` (array) and optional `equipment` (array). If the LLM returns extra keys, wrong types, or invalid UUIDs, the API returns **422 Unprocessable Entity**.

To avoid that:

1. **Instruct the LLM** — In your prompt, add: “Return only valid JSON that conforms to the Open-FDD import schema: top-level keys `points` and `equipment` only; each point has the fields listed in the prompt; equipment items use `equipment_name`, `site_id`, optional `feeds` / `fed_by`, optional `engineering` / `metadata`.”

2. **Use the API’s JSON Schema** — The OpenAPI spec at **GET /openapi.json** (or **GET /docs** and “openapi.json”) includes a **schema** for the import body. You can:
   - Export that schema (e.g. the `DataModelImportBody` and nested `PointImportRow` / `EquipmentImportRow` from the spec) and give it to the LLM: “Return JSON that validates against this schema.”
   - Or run a local **validation step** before pasting into the UI: validate the LLM’s JSON against the same schema (e.g. with a small script or tool that loads the schema and runs `jsonschema.validate`). If it passes, PUT /data-model/import will accept it (aside from referential issues like missing site_id).
3. **Common failure: `site_id` is not a UUID** — `PUT /data-model/import` expects `points[].site_id` to be either:
   - a UUID string (as returned by `GET /data-model/export`), or
   - `null`/omitted (so the backend can resolve it from `points[].site_name`).

   If you see an error like:
   `site_id must be a valid UUID from GET /sites ... Got: 'BensOffice'`
   then your LLM replaced the UUID with the human-readable site name. Reinforce: **never** replace `site_id` with `site_name`; if the export has no UUID, keep `site_id` null and keep `site_name`.

4. **Pydantic in the repo** — The backend defines the import shape in **open_fdd/platform/api/data_model.py**: `DataModelImportBody`, `PointImportRow`, `EquipmentImportRow`. A script or pipeline can import those models and validate the LLM output (e.g. `DataModelImportBody.model_validate(json.loads(llm_output))`) before returning it to the human. That way the human only sees JSON that is known to parse on the backend.

---

## Mechanical engineer flow (short)

1. **Create site** (and optionally equipment) via API or UI; note **site_id**.
2. **Export** — GET /data-model/export?site_id=YourSiteName (or no filter for full dump).
3. **Upload to LLM** — Paste (a) the [canonical template above](#copy-paste-prompt-template-recommended) (or your saved copy of the same text), (b) **fault/rule context** (which faults you run + **YAML snippets when possible**), then (c) export JSON. Optionally include the import JSON Schema so the LLM returns a valid payload.
   - **Fault-first:** Answer the pre-flight questions (or let the model ask them) before treating polling as final.
   - **UUID reminder:** Never replace `points[].site_id` with a human-readable site name; keep the UUID from the export (see **Validate before import** below).
4. **Validate** — Run schema validation or Pydantic validation on the LLM reply so you know it will parse on the backend.
5. **Import** — PUT /data-model/import with the validated JSON.
6. **Run FDD / tests** — Trigger an FDD run or Sparkl (or other) tests as needed for the project.

---

## See also

- [AI-assisted data modeling](ai_assisted_tagging) — Export → tag → import and API contract.
- [Data model engineering](../howto/data_model_engineering) — `equipment.metadata.engineering`, import/export, TTL / SPARQL.
- [Technical reference](../appendix/technical_reference) — PyPI vs repo, LLM tagging workflow; full prompt is above on this page.
- [Fault rules overview](../rules/overview) and [Expression Rule Cookbook](../expression_rule_cookbook) — Rules and rule_input reference.
