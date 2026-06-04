/** Format BACnet poll status timestamp in site/local browser timezone. */
export function formatPollSampleAt(
  poll: { at?: string; at_local_display?: string; at_local?: string; site_timezone?: string } | null,
): string {
  if (!poll) return "";
  if (poll.at_local_display) {
    return poll.site_timezone
      ? `${poll.at_local_display} (${poll.site_timezone})`
      : poll.at_local_display;
  }
  const raw = poll.at_local || poll.at;
  if (!raw) return "";
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return String(raw);
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" });
}
