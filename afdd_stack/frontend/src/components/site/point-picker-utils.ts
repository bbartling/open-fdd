import type { Point } from "@/types/api";

/**
 * Normalized group key for equipment (unassigned points share one key).
 * Used so dropdown grouping matches the Points table and avoids duplicate headings.
 */
export function pointGroupKey(p: Point): string {
  return (p.equipment_id?.trim() || "") || "__unassigned__";
}

/**
 * Returns points deduplicated by id, preserving first occurrence order.
 * Dropdown must show exactly this set so it matches the Points table selectability.
 */
export function uniquePointsForDropdown(points: Point[]): Point[] {
  const seen = new Set<string>();
  return points.filter((p) => {
    if (seen.has(p.id)) return false;
    seen.add(p.id);
    return true;
  });
}
