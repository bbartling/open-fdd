/** Standard BACnet/Modbus/JSON/Haystack poll cadence options (Python-era parity). */
export const POLL_OPTIONS = [
  { seconds: 60, label: "1 min" },
  { seconds: 300, label: "5 min" },
  { seconds: 600, label: "10 min" },
  { seconds: 900, label: "15 min" },
] as const;

export type PollOption = (typeof POLL_OPTIONS)[number];

export function pollLabel(seconds: number): string {
  return POLL_OPTIONS.find((o) => o.seconds === seconds)?.label ?? (seconds > 0 ? `${seconds}s` : "off");
}
