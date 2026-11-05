/** Normalize chart/historian timestamps (ISO or epoch ms) for previews and sorting. */

export function parseTimestampMillis(value) {
  if (value == null) return null;
  if (typeof value === "number") {
    if (!Number.isFinite(value) || value < 1e11 || value > 1e14) return null;
    return value;
  }
  if (typeof value !== "string") return null;
  const s = value.trim();
  if (!s || s.includes("PrimitiveArray")) return null;
  if (/^\d{13}$/.test(s)) {
    const ms = Number(s);
    return Number.isFinite(ms) ? ms : null;
  }
  if (/^\d{4}-\d{2}-\d{2}(?:[T ]|$)/.test(s)) {
    const ms = Date.parse(s);
    return Number.isFinite(ms) ? ms : null;
  }
  return null;
}

export function formatSampleAge(isoOrMs, nowMs = Date.now()) {
  const ms = parseTimestampMillis(isoOrMs);
  if (ms == null) return "no sample";
  const deltaSec = Math.max(0, Math.floor((nowMs - ms) / 1000));
  if (deltaSec < 90) return "sample < 2 min ago";
  if (deltaSec < 3600) return `sample ${Math.round(deltaSec / 60)} min ago`;
  if (deltaSec < 86_400) return `sample ${Math.round(deltaSec / 3600)} h ago`;
  return `sample ${Math.round(deltaSec / 86_400)} d ago`;
}
