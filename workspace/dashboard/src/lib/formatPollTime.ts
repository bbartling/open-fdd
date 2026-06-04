/** Format BACnet poll status timestamp (prefer UTC `at`, else show site-local string verbatim). */
export function formatPollSampleAt(
  poll: { at?: string; at_local_display?: string; at_local?: string; site_timezone?: string } | null,
): string {
  if (!poll) return "";
  if (poll.at) {
    const d = new Date(poll.at);
    if (!Number.isNaN(d.getTime())) {
      const opts: Intl.DateTimeFormatOptions = { dateStyle: "medium", timeStyle: "medium" };
      if (poll.site_timezone) {
        return d.toLocaleString(undefined, { ...opts, timeZone: poll.site_timezone });
      }
      return d.toLocaleString(undefined, opts);
    }
  }
  if (poll.at_local_display) {
    return poll.site_timezone
      ? `${poll.at_local_display} (${poll.site_timezone})`
      : poll.at_local_display;
  }
  if (poll.at_local) {
    return poll.at_local;
  }
  return "";
}
