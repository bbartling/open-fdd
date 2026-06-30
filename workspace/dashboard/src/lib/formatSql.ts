/** Lightweight SQL layout for the FDD editor (no external formatter dependency). */

const TOP_LEVEL = ["SELECT", "FROM", "WHERE", "GROUP BY", "HAVING", "ORDER BY", "WINDOW"] as const;

const KEYWORDS = [
  ...TOP_LEVEL,
  "CASE",
  "WHEN",
  "THEN",
  "ELSE",
  "END",
  "AND",
  "OR",
  "AS",
  "IS",
  "NULL",
  "NOT",
  "IN",
  "LIKE",
  "BETWEEN",
  "DISTINCT",
  "LIMIT",
  "JOIN",
  "LEFT",
  "RIGHT",
  "INNER",
  "OUTER",
  "ON",
  "UNION",
  "ALL",
  "WITH",
];

function upperKeywords(sql: string): string {
  let s = sql;
  for (const kw of KEYWORDS) {
    s = s.replace(new RegExp(`\\b${kw.replace(/ /g, "\\s+")}\\b`, "gi"), kw);
  }
  return s.replace(/\bTRUE\b/gi, "true").replace(/\bFALSE\b/gi, "false");
}

/** Split comma-separated list respecting single-quoted strings and parentheses. */
function splitCommaList(input: string): string[] {
  const parts: string[] = [];
  let buf = "";
  let depth = 0;
  let inStr: "'" | '"' | null = null;

  for (let i = 0; i < input.length; i++) {
    const ch = input[i];
    if (inStr) {
      buf += ch;
      if (ch === inStr && input[i - 1] !== "\\") inStr = null;
      continue;
    }
    if (ch === "'" || ch === '"') {
      inStr = ch;
      buf += ch;
      continue;
    }
    if (ch === "(") {
      depth++;
      buf += ch;
      continue;
    }
    if (ch === ")") {
      depth = Math.max(0, depth - 1);
      buf += ch;
      continue;
    }
    if (ch === "," && depth === 0) {
      parts.push(buf.trim());
      buf = "";
      continue;
    }
    buf += ch;
  }
  if (buf.trim()) parts.push(buf.trim());
  return parts;
}

function formatCaseBlock(expr: string): string {
  if (!/\bCASE\b/i.test(expr)) return expr.replace(/\s+/g, " ").trim();

  let s = expr.trim().replace(/\s+/g, " ");
  s = s.replace(/\bCASE\s+/i, "CASE\n");
  s = s.replace(/\s+\bWHEN\b\s*/gi, "\n  WHEN ");
  s = s.replace(/\s+\bELSE\b\s*/gi, "\n  ELSE ");
  s = s.replace(/\s+\bEND\b\s*/gi, "\nEND ");

  return s
    .split("\n")
    .map((line) => line.trimEnd())
    .join("\n");
}

function formatSelectColumn(expr: string): string {
  return formatCaseBlock(expr);
}

function simpleFormat(oneLine: string): string {
  let s = upperKeywords(oneLine);
  for (const kw of TOP_LEVEL) {
    s = s.replace(new RegExp(`\\s+${kw}\\b`), `\n${kw}`);
  }
  s = s.replace(/\bCASE\b/g, "\nCASE");
  s = s.replace(/\bWHEN\b/g, "\n  WHEN");
  s = s.replace(/\bELSE\b/g, "\n  ELSE");
  s = s.replace(/\bEND\b/g, "\nEND");
  return s
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .join("\n");
}

export function formatSql(sql: string): string {
  const raw = sql.trim();
  if (!raw) return "";

  const oneLine = upperKeywords(raw.replace(/\s+/g, " "));

  const fromIdx = oneLine.search(/\bFROM\b/i);
  if (fromIdx < 0) return simpleFormat(oneLine);

  const selectPart = oneLine.slice(0, fromIdx).replace(/^SELECT\s+/i, "").trim();
  const rest = oneLine.slice(fromIdx);

  const whereMatch = rest.match(/^FROM\s+(.+?)(?:\s+WHERE\s+(.+))?$/i);
  if (!whereMatch) return simpleFormat(oneLine);

  const [, fromClause, whereClause] = whereMatch;
  const columns = splitCommaList(selectPart);

  const lines: string[] = ["SELECT"];
  for (let i = 0; i < columns.length; i++) {
    const body = formatSelectColumn(columns[i]);
    const needsComma = i < columns.length - 1;
    if (body.includes("\n")) {
      const subLines = body.split("\n");
      for (let j = 0; j < subLines.length; j++) {
        const comma = needsComma && j === subLines.length - 1 ? "," : "";
        lines.push(`  ${subLines[j]}${comma}`);
      }
    } else {
      lines.push(`  ${body}${needsComma ? "," : ""}`);
    }
  }
  lines.push(`FROM ${fromClause.trim()}`);
  if (whereClause?.trim()) lines.push(`WHERE ${whereClause.trim()}`);

  return lines.join("\n");
}

export const DEFAULT_TELEMETRY_PIVOT_SQL = `SELECT
  timestamp,
  equipment_id,
  oa_t,
  CASE
    WHEN oa_t IS NULL THEN false
    WHEN oa_t < 40.0 THEN true
    WHEN oa_t > 110.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:local-test-equipment'`;
