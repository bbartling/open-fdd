---
title: LLM workflow (export + rules + validate → import)
parent: Data modeling
nav_order: 5
---

# LLM workflow: one prompt, export JSON, rules, and validated import

This page describes a **single upload** workflow for mechanical engineers: send the **canonical prompt**, the **data-model export JSON**, and (optionally) the **rules you want to use** to an LLM; get back import-ready JSON; **validate** it so you know it will parse on the Open-FDD backend; then **PUT /data-model/import** and run FDD (or Sparkl/tests) as needed.

> **Automated path available:** External OpenAI-compatible agents (for example Open‑Claw) can automate the same flow by calling `GET /data-model/export`, fetching platform documentation context from `GET /model-context/docs`, and then calling `PUT /data-model/import` with validated import JSON. The manual copy-paste workflow below always works too.

---

## What you upload to the LLM

1. **The canonical prompt** — Use **[AI-assisted data modeling](ai_assisted_tagging)** (section *LLM prompt and agent guidelines*), the inline template **below** on this page (“Copy/paste prompt template”), or the [Technical reference — LLM tagging workflow](../appendix/technical_reference#llm-tagging-workflow). You can copy from this page or keep an optional local mirror (e.g. `pdf/canonical_llm_prompt.txt`) for agents. The prompt must tell the LLM to return only `{"points": [...], "equipment": [...]}` with Brick types, rule_input slugs, equipment_name, feeds/fed_by, polling, and units.

2. **The export JSON** — From **GET /data-model/export** (optionally `?site_id=YourSiteName`). Example shape: one array of objects with `point_id`, `bacnet_device_id`, `object_identifier`, `object_name`, `external_id`, `site_id`, `site_name`, `equipment_id`, `equipment_name`, `brick_type`, `rule_input`, `unit`, `polling`. Unimported rows have `point_id: null` and null tagging fields; the LLM fills those and can set `site_id` if you pre-create the site.

3. **Rules for this project (optional)** — So the LLM knows which **rule_input** slugs and Brick types your FDD rules expect. You can:
   - Point the LLM at the **[Fault rules overview](../rules/overview)** and **[Expression Rule Cookbook](../rules/expression_rule_cookbook)** (AHU, chiller, weather, advanced recipes). The cookbook is the main reference for rule_input names and expression patterns.
   - Or paste **YAML** from your project’s rules (e.g. from `stack/rules/` or your own rule files). The LLM can align `rule_input` with the inputs those rules use (e.g. `sat`, `rat`, `zone_temp`, `sf_status`).

> For best polling decisions, include your actual rule YAMLs. Otherwise many BACnet points may be correctly tagged but still unnecessary for FDD/trending and should remain `polling: false`.

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

2. ADD or FILL these fields:
- brick_type
- rule_input
- polling
- unit
- equipment_name

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

5. unit:
Fill unit when known.
Use standard abbreviations:
- temperature -> "degF" or "°F"
- percentage -> "percent" or "%"
- airflow -> "cfm"
- binary / boolean -> "0/1"
- power -> "W"
- irradiance -> "W/m²"
If unknown, use null.

6. polling:
Set polling=true for points that should be logged for FDD, plotting, or trend analysis.
Set polling=false for points that are not useful for FDD/trending.
If unsure, prefer false.

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

8. fallback behavior:
If uncertain:
- brick_type = null
- rule_input = null
- unit = null
- polling = false

--------------------------------------------------
EQUIPMENT RULES
--------------------------------------------------

Create an "equipment" array with one entry per equipment.

Each equipment item must use this shape:

{
  "equipment_name": "AHU-1",
  "site_id": "<same site_id as the points>",
  "feeds": ["VAV-1"]
}

or

{
  "equipment_name": "VAV-1",
  "site_id": "<same site_id as the points>",
  "fed_by": ["AHU-1"]
}

Rules:
- Use equipment names only
- Do not use equipment UUIDs
- Preserve the exact site_id from the export
- Include feeds/fed_by only when supported by the provided data or clearly specified by the user
- Do not invent mechanical relationships unless they are explicitly given or obvious from the provided context

--------------------------------------------------
STRICT OUTPUT REQUIREMENTS
--------------------------------------------------

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

---

## Where the rules live

| What | Where |
|------|--------|
| **Fault rules overview** | [docs/rules/overview](../rules/overview) — FDD rule types, YAML format, Brick-driven inputs. |
| **Expression Rule Cookbook** | [docs/rules/expression_rule_cookbook](../rules/expression_rule_cookbook) — AHU, chiller, weather, and advanced recipes; **rule_input** examples and expression patterns. |
| **Actual YAML rule files** | `stack/rules/` in the repo (or your `rules_dir`). The ME can upload or paste snippets so the LLM uses the same input names. |

The cookbook is **not** a fault rule file itself; it’s documentation. The **rules you want to use** are the YAML files in `stack/rules/` (or your project’s rules). For the LLM, you can either paste that YAML or say “use rule_input slugs from the Expression Rule Cookbook (sat, rat, zone_temp, …).”

---

## Feeds / fed_by (HVAC topology)

- **feeds** — This equipment supplies another (e.g. AHU feeds VAV).
- **fed_by** — This equipment is supplied by another (e.g. VAV fed_by AHU).

If topology is not known confidently, omit feeds/fed_by rather than guessing. You can add or refine relationships later.

---

## Validate before import (so backend CRUD accepts it)

The Open-FDD **PUT /data-model/import** endpoint expects a body that matches the **DataModelImportBody** Pydantic model: exactly `points` (array) and optional `equipment` (array). If the LLM returns extra keys, wrong types, or invalid UUIDs, the API returns **422 Unprocessable Entity**.

To avoid that:

1. **Instruct the LLM** — In your prompt, add: “Return only valid JSON that conforms to the Open-FDD import schema: top-level keys `points` and `equipment` only; each point has the fields listed in the prompt; equipment items use `equipment_name`, `site_id`, `feeds`, `fed_by`.”

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
3. **Upload to LLM** — Paste (a) the [canonical template above](#copy-paste-prompt-template-recommended) (or your saved copy of the same text), (b) export JSON, (c) optional rules (cookbook link or YAML snippets). Optionally include the import JSON Schema so the LLM returns valid payload.
   - **UUID reminder:** Never replace `points[].site_id` with a human-readable site name; keep the UUID from the export (see **Validate before import** below).
4. **Validate** — Run schema validation or Pydantic validation on the LLM reply so you know it will parse on the backend.
5. **Import** — PUT /data-model/import with the validated JSON.
6. **Run FDD / tests** — Trigger an FDD run or Sparkl (or other) tests as needed for the project.

---

## See also

- [AI-assisted data modeling](ai_assisted_tagging) — Export → tag → import and API contract.
- [Technical reference](../appendix/technical_reference) — PyPI vs repo, LLM tagging workflow; full prompt is above on this page.
- [Fault rules overview](../rules/overview) and [Expression Rule Cookbook](../rules/expression_rule_cookbook) — Rules and rule_input reference.
