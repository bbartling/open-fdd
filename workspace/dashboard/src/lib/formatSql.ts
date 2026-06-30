/** Lightweight SQL layout for the FDD editor (no external formatter dependency). */
export function formatSql(sql: string): string {
  let s = sql.trim().replace(/\s+/g, " ");
  if (!s) return s;
  const breaks = [
    "SELECT",
    "FROM",
    "WHERE",
    "GROUP BY",
    "HAVING",
    "ORDER BY",
    "WINDOW",
    "CASE",
    "WHEN",
    "THEN",
    "ELSE",
    "END",
    "AND",
    "OR",
  ];
  for (const kw of breaks) {
    const re = new RegExp(`\\b${kw}\\b`, "gi");
    s = s.replace(re, `\n${kw.toUpperCase()}`);
  }
  return s
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .join("\n")
    .replace(/\n+/g, "\n")
    .trim();
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
