import FaultTimeline, { type FaultTimelinePoint } from "./FaultTimeline";

type Props = {
  ruleId: string;
  equipmentId: string;
  gateMode?: string;
  points: FaultTimelinePoint[];
  height?: number;
};

/** Result-linked Plotly chart: preserves exact rule_id + equipment_id in the title. */
export default function RuleResultChart({
  ruleId,
  equipmentId,
  gateMode,
  points,
  height = 260,
}: Props) {
  const title = gateMode
    ? `${ruleId} · ${equipmentId} (${gateMode})`
    : `${ruleId} · ${equipmentId}`;
  return <FaultTimeline title={title} points={points} height={height} />;
}
