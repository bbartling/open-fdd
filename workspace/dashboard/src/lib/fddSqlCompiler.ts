import type { FddInput, SchemaTable, SqlCompileResult } from "../components/sqlFdd/types";

const DIALECT = "DataFusion";

/** Grafana-style read-only guardrails for Open-FDD historian SQL. */
export function compileNaturalLanguagePrompt(args: {
  userPrompt: string;
  equipmentId: string;
  timeColumn?: string;
  schema: SchemaTable[];
  fddInputs: FddInput[];
  defaultLimit?: number;
}): SqlCompileResult {
  const prompt = args.userPrompt.trim();
  const timeColumn = args.timeColumn ?? "timestamp";
  const limit = args.defaultLimit ?? 50;

  if (!prompt) {
    return { ok: false, error: "Enter a natural language request to compile.", dialect: DIALECT };
  }
  if (!args.equipmentId.trim()) {
    return { ok: false, error: "Select equipment before compiling — SQL must scope to one device.", dialect: DIALECT };
  }

  const pivot = args.schema.find((t) => t.name === "telemetry_pivot");
  const columnNames = normalizeColumns(pivot).map((c) => c.name);
  if (!columnNames.length) {
    return { ok: false, error: "Schema missing telemetry_pivot — refresh schema explorer.", dialect: DIALECT };
  }

  const lower = prompt.toLowerCase();
  const input = matchFddInput(lower, args.fddInputs);
  if (!input) {
    const known = args.fddInputs.map((i) => i.id).join(", ");
    return {
      ok: false,
      error: `Could not map prompt to a known FDD column. Available: ${known}`,
      dialect: DIALECT,
    };
  }
  if (!columnNames.includes(input.id)) {
    return {
      ok: false,
      error: `Column '${input.id}' is not in telemetry_pivot for this site historian.`,
      dialect: DIALECT,
    };
  }

  const operator = matchOperator(lower);
  const threshold = matchThreshold(lower, input);
  if (threshold == null) {
    return {
      ok: false,
      error: `Specify a numeric threshold for ${input.label} (e.g. "above 110").`,
      dialect: DIALECT,
    };
  }

  const wantsFault = /fault|fdd|alarm|violation|out of range|anomaly/.test(lower);
  const wantsTop = lower.match(/\btop\s+(\d+)\b/);
  const rowLimit = wantsTop ? Number(wantsTop[1]) : limit;
  const equip = args.equipmentId.replace(/'/g, "''");

  let sql: string;
  let explanation: string;

  if (wantsFault) {
    sql = [
      "SELECT",
      `  ${timeColumn}, equipment_id, ${input.id},`,
      `  CASE WHEN ${input.id} IS NULL THEN false WHEN ${input.id} ${operator} ${threshold} THEN true ELSE false END AS fault_raw`,
      "FROM telemetry_pivot",
      `WHERE equipment_id = '${equip}'`,
      `  AND $__timeFilter(${timeColumn})`,
      `LIMIT ${rowLimit}`,
    ].join("\n");
    explanation = `FDD rule SQL: flag ${input.label} (${input.id}) when value ${operator} ${threshold}, scoped to selected equipment, with Open-FDD time macro and LIMIT ${rowLimit}.`;
  } else {
    sql = [
      "SELECT",
      `  ${timeColumn}, equipment_id, ${input.id}`,
      "FROM telemetry_pivot",
      `WHERE equipment_id = '${equip}'`,
      `  AND $__timeFilter(${timeColumn})`,
      `ORDER BY ${timeColumn} DESC`,
      `LIMIT ${rowLimit}`,
    ].join("\n");
    explanation = `Preview query for ${input.label} on selected equipment; time range via $__timeFilter(${timeColumn}), limited to ${rowLimit} rows.`;
  }

  return { ok: true, sql, explanation, dialect: DIALECT };
}

function normalizeColumns(table: SchemaTable | undefined): { name: string; type: string }[] {
  if (!table?.columns?.length) return [];
  if (typeof table.columns[0] === "string") {
    return (table.columns as string[]).map((name) => ({ name, type: "DOUBLE" }));
  }
  return (table.columns as { name: string; type: string }[]).map((c) => ({
    name: c.name,
    type: c.type ?? "DOUBLE",
  }));
}

function matchFddInput(lower: string, inputs: FddInput[]): FddInput | null {
  for (const i of inputs) {
    if (lower.includes(i.id.toLowerCase())) return i;
  }
  for (const i of inputs) {
    const label = i.label.toLowerCase();
    if (label && lower.includes(label)) return i;
  }
  const aliases: Record<string, string> = {
    "outside air": "oa_t",
    "oa temp": "oa_t",
    "supply air": "sat",
    "zone temp": "zn_t",
    humidity: "oa_h",
    occupancy: "occ",
    "fan command": "fan_cmd",
  };
  for (const [phrase, id] of Object.entries(aliases)) {
    if (lower.includes(phrase)) {
      return inputs.find((i) => i.id === id) ?? null;
    }
  }
  return inputs[0] ?? null;
}

function matchOperator(lower: string): string {
  if (/below|under|less than|<(?!=)/.test(lower) && !/less than or equal|<=/.test(lower)) return "<";
  if (/above|over|greater than|exceed/.test(lower) && !/greater than or equal|>=/.test(lower)) return ">";
  if (/below|under|less than|<=|≤/.test(lower)) return "<=";
  if (/above|over|greater than|>=|≥|exceed/.test(lower)) return ">=";
  return ">";
}

function matchThreshold(lower: string, input: FddInput): number | null {
  const m = lower.match(/(-?\d+(?:\.\d+)?)/);
  if (m) return Number(m[1]);
  if (input.id === "oa_t") return 110;
  if (input.id === "sat" || input.id === "duct_t" || input.id === "zn_t") return 75;
  if (input.id === "oa_h") return 90;
  return null;
}

/** Expand Grafana-style macros for DataFusion test runs (full historian window). */
export function expandTimeMacros(sql: string, timeColumn = "timestamp"): string {
  const macro = `$__timeFilter(${timeColumn})`;
  if (!sql.includes(macro)) return sql;
  const replacement = `${timeColumn} IS NOT NULL`;
  return sql.split(macro).join(replacement);
}
