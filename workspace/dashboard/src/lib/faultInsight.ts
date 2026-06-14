import type { FaultAnalytics } from "./dashboardStream";

const CONFIG_LABELS: Record<string, string> = {
  bounds_low: "Low limit",
  bounds_high: "High limit",
  bounds_low_rh: "Low RH limit",
  bounds_high_rh: "High RH limit",
  value_column: "Historian column",
  window_samples: "Window (samples)",
  flatline_tolerance: "Flatline tolerance",
  max_spread: "Max spread",
  temp_unit: "Temperature units",
};

function num(v: unknown): number | undefined {
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

/** Operator-facing rule threshold lines from saved config. */
export function ruleConfigLines(config?: Record<string, unknown>): { label: string; value: string }[] {
  if (!config || typeof config !== "object") return [];
  const lines: { label: string; value: string }[] = [];
  for (const [key, label] of Object.entries(CONFIG_LABELS)) {
    const raw = config[key];
    if (raw === undefined || raw === null || String(raw).trim() === "") continue;
    lines.push({ label, value: String(raw) });
  }
  return lines;
}

/** Plain-language explanation of why an FDD rule fired. */
export function describeFaultCause(
  analytics?: FaultAnalytics,
  ruleConfig?: Record<string, unknown>,
): string {
  const lo = analytics?.bounds_low ?? num(ruleConfig?.bounds_low) ?? num(ruleConfig?.bounds_low_rh);
  const hi = analytics?.bounds_high ?? num(ruleConfig?.bounds_high) ?? num(ruleConfig?.bounds_high_rh);
  const avg = analytics?.avg_value_fault;
  const min = analytics?.min_value_fault;
  const max = analytics?.max_value_fault;
  const unit = analytics?.value_unit || (ruleConfig?.bounds_low_rh != null ? "%RH" : "°F");
  const col = (analytics?.value_columns || [])[0] || String(ruleConfig?.value_column || "").trim();

  const parts: string[] = [];

  if (lo != null && hi != null && avg != null) {
    const band = `${lo}–${hi}${unit}`;
    if (avg < lo) {
      parts.push(
        `Readings averaged ${avg}${unit}, below the configured band (${band}). The rule flags when values stay outside that range.`,
      );
    } else if (avg > hi) {
      parts.push(
        `Readings averaged ${avg}${unit}, above the configured band (${band}). The rule flags when values stay outside that range.`,
      );
    } else {
      parts.push(
        `Recent samples averaged ${avg}${unit} within band ${band}, but enough flagged samples crossed the limit during the lookback window.`,
      );
    }
    if (min != null && max != null && (min !== avg || max !== avg)) {
      parts.push(`Flagged samples ranged from ${min} to ${max}${unit}.`);
    }
  } else if (avg != null) {
    parts.push(`Flagged samples averaged ${avg}${unit} during the lookback window.`);
  }

  if (analytics?.fault_samples != null && analytics?.total_samples != null) {
    const pct = analytics.total_samples
      ? Math.round((analytics.fault_samples / analytics.total_samples) * 100)
      : 0;
    parts.push(
      `${analytics.fault_samples} of ${analytics.total_samples} recent samples (${pct}%) triggered the rule.`,
    );
  }

  if (analytics?.estimated_fault_duration_label) {
    parts.push(`Fault-active time in lookback: about ${analytics.estimated_fault_duration_label}.`);
  }

  if (col) {
    parts.push(`Historian column: ${col}.`);
  }

  return parts.join(" ") || "The rule matched enough recent historian samples to raise this alert.";
}

/** Trend plot deep link with FDD overlays when equipment is known. */
export function plotLinkForFault(equipmentId?: string, siteId?: string): string {
  const params = new URLSearchParams();
  params.set("fdd", "1");
  if (siteId?.trim()) params.set("site_id", siteId.trim());
  if (equipmentId?.trim()) params.set("device_id", equipmentId.trim());
  const qs = params.toString();
  return qs ? `/plot?${qs}` : "/plot?fdd=1";
}
