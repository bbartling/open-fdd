import type { ModelPayload } from "./modelImport";

/** Single paste block for external LLMs: system prompt + current model export. */
export function buildLlmModelBundle(prompt: string, model: ModelPayload): string {
  const json = JSON.stringify(model, null, 2);
  return (
    `${prompt.trim()}\n\n` +
    `---\n` +
    `CURRENT data_model_export.json (from GET /api/model/export — included for your session):\n\n` +
    "```json\n" +
    json +
    "\n```\n\n" +
    `Respond with import_ready_json only when asked, preserving BACnet point ids and external_id column names.`
  );
}

/** Prompt + commissioning export (Haystack + FDD rule bindings). */
export function buildLlmCommissioningBundle(prompt: string, bundle: Record<string, unknown>): string {
  const json = JSON.stringify(bundle, null, 2);
  return (
    `${prompt.trim()}\n\n` +
    `---\n` +
    `CURRENT openfdd-commissioning.json (GET /api/model/commissioning-export):\n\n` +
    "```json\n" +
    json +
    "\n```\n\n" +
    `Respond with a single JSON object containing sites, equipment, points (optional fdd_rule_ids per point), and fdd_rules when updating assignments.`
  );
}
