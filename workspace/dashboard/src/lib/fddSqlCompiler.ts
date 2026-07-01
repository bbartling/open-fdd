/** Expand Grafana-style macros for DataFusion test runs (full historian window). */
export function expandTimeMacros(sql: string, timeColumn = "timestamp"): string {
  const macro = `$__timeFilter(${timeColumn})`;
  if (!sql.includes(macro)) return sql;
  const replacement = `${timeColumn} IS NOT NULL`;
  return sql.split(macro).join(replacement);
}
