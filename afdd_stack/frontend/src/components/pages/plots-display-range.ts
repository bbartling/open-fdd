/**
 * Only replace display range state when start/end actually change.
 * Used by PlotsPage to avoid "Maximum update depth exceeded" from TrendChart's onDisplayRangeChange effect.
 */
export function displayRangeUpdater(
  prev: { start: string; end: string } | null,
  s: string,
  e: string,
): { start: string; end: string } {
  return prev?.start === s && prev?.end === e ? prev : { start: s, end: e };
}
