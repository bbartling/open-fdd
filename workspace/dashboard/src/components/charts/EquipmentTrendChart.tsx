import FaultTimeline, { type FaultTimelinePoint } from "./FaultTimeline";

type Props = {
  equipmentId: string;
  points: FaultTimelinePoint[];
  height?: number;
};

/** Equipment-scoped trend of operational / fault masks (shared FaultTimeline). */
export default function EquipmentTrendChart({ equipmentId, points, height = 240 }: Props) {
  return <FaultTimeline title={`Equipment · ${equipmentId}`} points={points} height={height} />;
}
