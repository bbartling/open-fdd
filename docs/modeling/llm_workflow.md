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

1. **The canonical prompt** — From the [README](https://github.com/bbartling/open-fdd#ai-assisted-data-modeling) (or [Technical reference](../appendix/technical_reference#llm-tagging-workflow)): the full text that tells the LLM to return only `{"points": [...], "equipment": [...]}` with Brick types, rule_input slugs, equipment_name, feeds/fed_by, polling, and units.

2. **The export JSON** — From **GET /data-model/export** (optionally `?site_id=YourSiteName`). Example shape: one array of objects with `point_id`, `bacnet_device_id`, `object_identifier`, `object_name`, `external_id`, `site_id`, `site_name`, `equipment_id`, `equipment_name`, `brick_type`, `rule_input`, `unit`, `polling`. Unimported rows have `point_id: null` and null tagging fields; the LLM fills those and can set `site_id` if you pre-create the site.

3. **Rules for this project (optional)** — So the LLM knows which **rule_input** slugs and Brick types your FDD rules expect. You can:
   - Point the LLM at the **[Fault rules overview](../rules/overview)** and **[Expression Rule Cookbook](../rules/expression_rule_cookbook)** (AHU, chiller, weather, advanced recipes). The cookbook is the main reference for rule_input names and expression patterns.
   - Or paste **YAML** from your project’s rules (e.g. from `stack/rules/` or your own rule files). The LLM can align `rule_input` with the inputs those rules use (e.g. `sat`, `rat`, `zone_temp`, `sf_status`).

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
then your LLM replaced the UUID with the human-readable site name.

Model instruction to paste into your LLM (manual tagging):
```text
For every point/equipment:
- site_id must be the exact UUID string from the export JSON.
- Never replace site_id with site_name (a label).
- If site_id is missing/unknown in the export, keep it null and keep site_name.
```

3. **Pydantic in the repo** — The backend defines the import shape in **open_fdd/platform/api/data_model.py**: `DataModelImportBody`, `PointImportRow`, `EquipmentImportRow`. A script or pipeline can import those models and validate the LLM output (e.g. `DataModelImportBody.model_validate(json.loads(llm_output))`) before returning it to the human. That way the human only sees JSON that is known to parse on the backend.

---

## Mechanical engineer flow (short)

1. **Create site** (and optionally equipment) via API or UI; note **site_id**.
2. **Export** — GET /data-model/export?site_id=YourSiteName (or no filter for full dump).
3. **Upload to LLM** — Paste (a) canonical prompt, (b) export JSON, (c) optional rules (cookbook link or YAML snippets). Optionally include the import JSON Schema so the LLM returns valid payload.
   - If you are using a **manual/external** LLM tagging workflow (no in-house agent), you can paste this as a hard instruction to your LLM system/developer prompt. The UUID and equipment rules below match the [Model instruction](#model-instruction-to-paste-into-your-llm-manual-tagging) above; keep both in sync when requirements change.
```text
Return ONLY valid Open-FDD import JSON with exactly two top-level keys:
{
  "points": [...],
  "equipment": [...]
}

Hard rules:
- Preserve every field from the export unless explicitly tagging it.
- Keep points[].site_id EXACTLY as provided in the export JSON.
- Keep points[].equipment_id EXACTLY as provided in the export JSON.
- NEVER replace site_id or equipment_id with site_name or equipment_name.
- If site_id is null in the export, keep it null.
- If equipment_id is null in the export, keep it null.
- NEVER invent UUIDs or placeholder strings.
- Use equipment_name only as a label for grouping/tagging points.
- Only populate the top-level equipment[] array if real equipment UUIDs are provided from GET /equipment or already exist in the export.
- If real equipment UUIDs are not available, return "equipment": [].
- Add brick_type, rule_input, unit, polling, and equipment_name where appropriate.
- Do not guess feeds/fed_by unless explicitly confirmed by the engineer.
```
4. **Validate** — Run schema validation or Pydantic validation on the LLM reply so you know it will parse on the backend.
5. **Import** — PUT /data-model/import with the validated JSON.
6. **Run FDD / tests** — Trigger an FDD run or Sparkl (or other) tests as needed for the project.

---

## See also

- [AI-assisted data modeling](ai_assisted_tagging) — Export → tag → import and API contract.
- [Technical reference](../appendix/technical_reference) — Full prompt text, PyPI vs repo, LLM tagging workflow.
- [Fault rules overview](../rules/overview) and [Expression Rule Cookbook](../rules/expression_rule_cookbook) — Rules and rule_input reference.
