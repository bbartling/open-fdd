export type ModelPayload = {
  sites: Array<Record<string, unknown>>;
  equipment: Array<Record<string, unknown>>;
  points: Array<Record<string, unknown>>;
};

export function parseImportPayload(input: string): ModelPayload {
  const raw = String(input || "").trim();
  if (!raw) {
    throw new Error("JSON input is empty.");
  }
  let parsed: unknown;
  try {
    parsed = parseJsonLenient(raw);
  } catch {
    const fromSections = extractImportJsonFromFileSections(raw);
    if (!fromSections) {
      throw new Error(
        "Could not parse JSON. Paste plain import JSON, a fenced ```json block, or === FILE: open_fdd_data_model_import_ready.json === sections.",
      );
    }
    parsed = fromSections;
  }
  return validateImportShape(extractImportShape(parsed));
}

function parseJsonLenient(raw: string): unknown {
  const attempts: string[] = [raw];
  const fenced = extractJsonFence(raw);
  if (fenced) {
    attempts.push(fenced);
  }
  for (const candidate of attempts) {
    try {
      return JSON.parse(candidate);
    } catch {
      // continue
    }
  }
  throw new Error("Invalid JSON.");
}

function extractJsonFence(text: string): string | null {
  const m = text.match(/```(?:json)?\s*([\s\S]*?)\s*```/i);
  return m?.[1]?.trim() || null;
}

function extractImportJsonFromFileSections(text: string): unknown | null {
  const re = /^===\s*FILE:\s*([^\n]+?)\s*===\s*\n([\s\S]*?)(?=^===\s*FILE:|$)/gm;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    const name = m[1].trim().toLowerCase();
    const body = m[2].trim();
    if (!body) continue;
    const looksImport =
      name.includes("import_ready") || name.endsWith(".json") || name.includes("data_model");
    if (!looksImport) continue;
    try {
      return JSON.parse(body) as unknown;
    } catch {
      continue;
    }
  }
  return null;
}

function extractImportShape(parsed: unknown): unknown {
  if (parsed && typeof parsed === "object") {
    const obj = parsed as Record<string, unknown>;
    if (obj.import_ready_json && typeof obj.import_ready_json === "object") {
      return obj.import_ready_json;
    }
    if (obj.proposed_model_json && typeof obj.proposed_model_json === "object") {
      return obj.proposed_model_json;
    }
  }
  return parsed;
}

function validateImportShape(value: unknown): ModelPayload {
  const obj = value as Record<string, unknown>;
  if (!obj || typeof obj !== "object") {
    throw new Error("Model payload must be an object.");
  }
  const sites = Array.isArray(obj.sites) ? obj.sites : null;
  const equipment = Array.isArray(obj.equipment) ? obj.equipment : null;
  const points = Array.isArray(obj.points) ? obj.points : null;
  if (!sites || !equipment || !points) {
    throw new Error("Model JSON must include arrays: sites, equipment, points.");
  }
  return {
    sites: sites as Array<Record<string, unknown>>,
    equipment: equipment as Array<Record<string, unknown>>,
    points: points as Array<Record<string, unknown>>,
  };
}
