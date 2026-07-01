/** Display floats at two decimal places; pass through non-numbers unchanged. */
export function formatSensorValue(value: unknown, unit?: string): string {
  if (value == null || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "—";
  const rounded = n.toFixed(2);
  return unit ? `${rounded} ${unit}` : rounded;
}

export function formatRange(min: unknown, max: unknown, unit?: string): string {
  return `${formatSensorValue(min, unit)} – ${formatSensorValue(max, unit)}`;
}
