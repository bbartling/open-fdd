export type HostHistoryPoint = {
  at: string;
  cpu: number | null;
  mem: number | null;
};

export const HOST_HISTORY_MS = 60 * 60 * 1000;

/** Keep samples from the last hour, oldest first (FIFO trim). */
export function appendHostHistory(
  prev: HostHistoryPoint[],
  sample: HostHistoryPoint,
  nowMs: number = Date.now(),
): HostHistoryPoint[] {
  const cutoff = nowMs - HOST_HISTORY_MS;
  return [...prev, sample].filter((p) => new Date(p.at).getTime() >= cutoff);
}
