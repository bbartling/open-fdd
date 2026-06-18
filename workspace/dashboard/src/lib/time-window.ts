/** Shared history / report window presets (Trend plot + RCx report builder). */

export type WindowPreset = {
  id: string;
  label: string;
  hours?: number;
  range?: () => { start: string; end: string };
};

export type WindowSelection = {
  presetId: string;
  hours: number;
  start?: string;
  end?: string;
};

export function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

export function endOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth() + 1, 0, 23, 59, 59, 999);
}

export const HISTORY_PRESETS: WindowPreset[] = [
  { id: "1h", label: "1 hour", hours: 1 },
  { id: "6h", label: "6 hours", hours: 6 },
  { id: "24h", label: "24 hours", hours: 24 },
  { id: "3d", label: "3 days", hours: 72 },
  { id: "7d", label: "7 days", hours: 168 },
  { id: "14d", label: "14 days", hours: 336 },
  { id: "30d", label: "30 days", hours: 720 },
  {
    id: "mtd",
    label: "Month to date",
    range: () => {
      const now = new Date();
      return { start: startOfMonth(now).toISOString(), end: now.toISOString() };
    },
  },
  {
    id: "last-month",
    label: "Last month",
    range: () => {
      const now = new Date();
      const prev = new Date(now.getFullYear(), now.getMonth() - 1, 1);
      return { start: startOfMonth(prev).toISOString(), end: endOfMonth(prev).toISOString() };
    },
  },
  {
    id: "ytd",
    label: "Year to date",
    range: () => {
      const now = new Date();
      return { start: new Date(now.getFullYear(), 0, 1).toISOString(), end: now.toISOString() };
    },
  },
];

export function resolveHistoryPreset(id: string): WindowSelection {
  const preset = HISTORY_PRESETS.find((p) => p.id === id) || HISTORY_PRESETS.find((p) => p.id === "24h")!;
  if (preset.range) {
    const { start, end } = preset.range();
    return { presetId: preset.id, hours: 168, start, end };
  }
  return { presetId: preset.id, hours: preset.hours ?? 24 };
}

export function historyQueryParams(sel: WindowSelection, customStart?: string, customEnd?: string): URLSearchParams {
  const qs = new URLSearchParams();
  if (sel.presetId === "custom" && customStart && customEnd) {
    qs.set("hours", "168");
    qs.set("start", new Date(customStart).toISOString());
    qs.set("end", new Date(customEnd).toISOString());
    return qs;
  }
  if (sel.start && sel.end) {
    qs.set("hours", String(sel.hours));
    qs.set("start", sel.start);
    qs.set("end", sel.end);
    return qs;
  }
  qs.set("hours", String(sel.hours));
  return qs;
}

export function historyLabel(sel: WindowSelection, customStart?: string, customEnd?: string): string {
  if (sel.presetId === "custom" && customStart && customEnd) return "custom range";
  const preset = HISTORY_PRESETS.find((p) => p.id === sel.presetId);
  return preset?.label ?? `${sel.hours}h`;
}
