/** Shared BACnet supervisory override UI labels and badge helpers. */

export const EXPORT_OVERRIDE_REPORT_CSV_LABEL = "Export override report CSV";

export function otherOverrideCount(total: number, operator: number): number {
  return Math.max(0, total - operator);
}

export function operatorOverrideBadgeLabel(count: number): string {
  return `P8×${count}`;
}

export function genericOverrideBadgeLabel(): string {
  return "⚠ ovrd";
}
