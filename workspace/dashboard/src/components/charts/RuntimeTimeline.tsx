import FaultTimeline, { type FaultTimelinePoint } from "./FaultTimeline";

type Props = {
  equipmentId: string;
  points: FaultTimelinePoint[];
  height?: number;
};

/** Runtime / operational-proof timeline (uses operational lane when present). */
export default function RuntimeTimeline({ equipmentId, points, height = 200 }: Props) {
  const runtimeOnly = points.map((p) => ({
    timestamp: p.timestamp,
    operational: p.operational,
    raw: p.operational,
    confirmed: null,
  }));
  return (
    <FaultTimeline title={`Runtime · ${equipmentId}`} points={runtimeOnly} height={height} />
  );
}
