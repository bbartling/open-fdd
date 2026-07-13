import type { FaultTimelinePoint } from "../components/charts/FaultTimeline";

/** Normalize API series payloads into FaultTimeline points (preserves ids via caller). */
export function mapSeriesToFaultTimelinePoints(
  points: Array<Partial<FaultTimelinePoint> & { timestamp?: string }>,
): FaultTimelinePoint[] {
  return points
    .filter((p) => typeof p.timestamp === "string" && p.timestamp.length > 0)
    .map((p) => ({
      timestamp: p.timestamp as string,
      raw: p.raw ?? null,
      confirmed: p.confirmed ?? null,
      operational: p.operational,
    }));
}
