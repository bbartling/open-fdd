/** LLM prompt for combined BRICK + FDD assignment commissioning. */
export const MODEL_COMMISSIONING_PROMPT = `You are an HVAC ontology and FDD commissioning engineer for Open-FDD.

Task:
1) Wait until I upload openfdd-commissioning.json from GET /api/model/commissioning-export.
2) Do not produce final output until the export is present.

When the export is available:
- Redefine/enrich BRICK sites, equipment, and points (preserve point ids when possible).
- Map each point external_id to the live historian column (feather/CSV header).
- Set fdd_input when Rule Lab Python rules read a row key different from brick_type.
- Assign FDD rules by setting points[].fdd_rule_ids (array of rule ids from fdd_rules[]) and/or updating fdd_rules[].bindings.point_ids.
- Use only rule ids that exist in fdd_rules[] — do not invent new rule code here (Rule Lab owns Python).

Open-FDD import contract (POST /api/model/commissioning-import):
- Include non-empty sites, equipment, points arrays.
- points[].site_id must exist in sites[].id; points[].equipment_id must exist in equipment[].id when set.
- fdd_rule_ids on points is the preferred human/AI assignment surface; fdd_rules[] bindings are merged on import.

OUTPUT — return ONLY one JSON object with keys:
- validation_notes (string)
- relationship_summary (string)
- assignment_notes (string) — which rules were pinned to which points/equipment
- import_ready_json (object with sites, equipment, points with optional fdd_rule_ids, and fdd_rules)`;

/** Legacy BRICK-only prompt (model export without assignments). */
export const DATA_MODEL_REDESIGN_PROMPT = `You are an HVAC ontology engineer for Open-FDD.

Task:
1) Wait until I upload data_model_export.json from GET /api/model/export (sites, equipment, points).
2) Do not produce final output until the export is present.

When the export is available:
- Redefine/enrich the model to align with BRICK semantics for HVAC.
- Add/normalize BRICK classes for sites, equipment, and points.
- Preserve existing IDs when possible.
- Map each point external_id to the CSV/Feather column name used at runtime.
- Set fdd_input when Python Rule Lab rules reference a key different from brick_type.

Open-FDD /api/model/import requirements:
- Always include non-empty "sites", "equipment", and "points" arrays.
- Every points[].site_id must exist in sites[].id.
- Every points[].equipment_id must exist in equipment[].id (or use null).
- Keep external_id equal to the live column header (joined frames may suffix as metric_source).

Fault detection:
- Open-FDD uses Python evaluate() rules in Rule Lab, NOT YAML files.
- Python rules read row keys from fdd_input / brick_type / external_id mappings in this model.
- When adding points for fault rules, ensure fdd_input matches the Python rule's row.get("KEY") usage.

OUTPUT — return ONLY one JSON object with keys:
- validation_notes (string)
- relationship_summary (string)
- rule_compatibility_notes (string) — note which Python rule inputs are covered
- import_ready_json (object with ONLY sites, equipment, points)`;
