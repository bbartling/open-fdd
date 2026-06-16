import type { FaultAlert, FaultFamily } from "./dashboardStream";
import { describeFaultCause } from "./faultInsight";

export type DisplayFault = {
  id: string;
  severity: "critical" | "high" | "medium" | "info";
  severityLabel: string;
  title: string;
  symptom: string;
  detail: string;
  equipmentLabel: string;
  dataSource?: string;
  source?: string;
  meta: { label: string; value: string }[];
  underlying: FaultAlert[];
  plainEnglish: string;
  technical?: string;
  modelContext?: FaultAlert["model_context"];
};

function mapSeverity(sev: string): DisplayFault["severity"] {
  const s = sev.toLowerCase();
  if (s === "critical") return "critical";
  if (s === "warning") return "medium";
  if (s === "info") return "info";
  return "high";
}

function severityLabel(sev: DisplayFault["severity"]): string {
  if (sev === "critical") return "Critical";
  if (sev === "high") return "High";
  if (sev === "medium") return "Medium";
  return "Info";
}

function flattenFamilies(families: FaultFamily[]): FaultAlert[] {
  const out: FaultAlert[] = [];
  for (const fam of families) {
    for (const f of fam.faults) out.push(f);
  }
  return out;
}

function isHistorianLag(a: FaultAlert): boolean {
  const t = String(a.title || "").toLowerCase();
  return String(a.source || "") === "poll_health" && t.includes("historian");
}

function isBacnetOperatorOverride(a: FaultAlert): boolean {
  return String(a.source || "") === "bacnet_override";
}

function groupBacnetOverrides(alerts: FaultAlert[]): DisplayFault | null {
  const hits = alerts.filter(isBacnetOperatorOverride);
  if (!hits.length) return null;
  const lines = hits.slice(0, 6).map((a) => String(a.title || "").replace(/^OVERRIDE\s*/i, ""));
  const extra = hits.length > 6 ? ` (+${hits.length - 6} more)` : "";
  const worst = hits.some((a) => a.severity === "critical") ? "critical" : "medium";
  return {
    id: "group-bacnet-overrides",
    severity: worst,
    severityLabel: severityLabel(worst),
    title: `BACnet operator overrides (P8) — ${hits.length} active`,
    symptom: "Manual priority-8 writes on commandable points",
    detail: lines.join("; ") + extra,
    equipmentLabel: "Overrides",
    source: "bacnet_override",
    meta: [
      { label: "Override count", value: String(hits.length) },
      { label: "Priority", value: "P8 (operator manual)" },
      { label: "Fix", value: "Review BACnet tab → relinquish when done" },
    ],
    underlying: hits,
    plainEnglish:
      "One or more commandable BACnet points have a manual operator write at priority 8. Present value may not match the schedule until those overrides are released.",
    technical: hits
      .slice(0, 8)
      .map((a) => a.title)
      .join("\n"),
  };
}

function isModelFddInput(a: FaultAlert): boolean {
  const t = String(a.title || "").toLowerCase();
  const d = String(a.detail || "").toLowerCase();
  return (
    String(a.source || "") === "model_health" &&
    (t.includes("fdd_input") || d.includes("fdd_input"))
  );
}

function groupHistorianLag(alerts: FaultAlert[]): DisplayFault | null {
  const hits = alerts.filter(isHistorianLag);
  if (!hits.length) return null;
  const names = hits
    .map((a) => String(a.equipment_name || a.title?.split(":")[0] || "").trim())
    .filter(Boolean);
  const unique = [...new Set(names)];
  const preview = unique.slice(0, 4).join(", ");
  const extra = unique.length > 4 ? ` (+${unique.length - 4} more)` : "";
  const worst = hits.some((a) => a.severity === "critical") ? "critical" : "medium";
  return {
    id: "group-historian-lag",
    severity: worst,
    severityLabel: severityLabel(worst),
    title: preview + extra || "Multiple devices",
    symptom: "Historian behind live BACnet poll",
    detail: `Poll CSV is updating but feather columns are stale for ${unique.length} device(s). Check bridge ingest after poll cycles.`,
    equipmentLabel: preview + extra || "Multiple devices",
    source: "poll_health",
    meta: [
      { label: "Devices affected", value: String(unique.length) },
      { label: "Fix", value: "Verify ingest / feather sync" },
    ],
    underlying: hits,
    plainEnglish:
      "Live BACnet polling is working, but the historian (feather store) has not caught up for several VAVs and plant equipment. Operators still see old values in trends and rules until ingest completes.",
    technical: hits
      .slice(0, 8)
      .map((a) => `${a.title}${a.detail ? ` — ${a.detail}` : ""}`)
      .join("\n"),
  };
}

function groupFddInput(alerts: FaultAlert[]): DisplayFault | null {
  const hit = alerts.find(isModelFddInput);
  if (!hit) return null;
  const m = String(hit.title || "").match(/(\d+)\s+point/i);
  const n = m ? m[1] : "many";
  return {
    id: "group-fdd-input",
    severity: "medium",
    severityLabel: "Medium",
    title: "Data model",
    symptom: `${n} points missing fdd_input mapping`,
    detail: String(hit.detail || hit.title || ""),
    equipmentLabel: "Data model",
    source: "model_health",
    meta: [
      { label: "Impact", value: "Rules may not bind to BACnet columns" },
      { label: "Fix", value: "Set fdd_input when Python keys differ from brick_type" },
    ],
    underlying: [hit],
    plainEnglish:
      "Many BRICK points do not have an fdd_input alias. Python rules that reference a different column name than brick_type will not evaluate until those aliases are set on the Data Model tab.",
    technical: hit.detail || hit.title,
  };
}

function plainSymptom(a: FaultAlert, ctx: FaultAlert["model_context"]): string {
  const fromCtx = String(
    a.short_description || a.symptom || ctx?.short_description || ctx?.symptom || "",
  ).trim();
  if (fromCtx) return fromCtx;
  const rule = String(ctx?.rule_name || a.rule_name || "").trim();
  if (!rule) return String(a.detail || a.title || "Issue");
  return rule;
}

function alertToDisplay(a: FaultAlert, equipmentLabel: string): DisplayFault {
  const sev = mapSeverity(String(a.severity || "warning"));
  const ctx = a.model_context;
  const eqName = String(ctx?.equipment?.name || a.equipment_name || equipmentLabel || "Unknown device").trim();
  const eqType = ctx?.equipment?.type;
  const displayEq = eqType && eqType !== "—" ? `${eqName} — ${eqType}` : eqName;
  const symptom = plainSymptom(a, ctx);
  const dataSource = String(a.data_source || ctx?.data_source || "").trim();

  const meta: { label: string; value: string }[] = [];
  if (dataSource) meta.push({ label: "Data source", value: dataSource });
  if (ctx?.point?.name && ctx.point.name !== "not mapped") {
    meta.push({ label: "Point", value: ctx.point.name });
  }
  if (ctx?.historian_column || ctx?.point?.external_id) {
    meta.push({
      label: "Historian column",
      value: String(ctx?.historian_column || ctx?.point?.external_id || ""),
    });
  }
  if (ctx?.bacnet_summary && ctx.bacnet_summary !== "not available") {
    meta.push({ label: "BACnet", value: ctx.bacnet_summary });
  }
  if (a.analytics?.estimated_fault_duration_label) {
    meta.push({ label: "Duration", value: a.analytics.estimated_fault_duration_label });
  }
  if (a.analytics?.fault_samples != null && a.analytics?.total_samples != null) {
    meta.push({
      label: "Samples flagged",
      value: `${a.analytics.fault_samples} / ${a.analytics.total_samples}`,
    });
  }

  return {
    id: String(a.id || `${a.source}-${a.title}`),
    severity: sev,
    severityLabel: severityLabel(sev),
    title: eqName,
    symptom,
    detail: String(a.detail || ""),
    equipmentLabel: displayEq,
    dataSource: dataSource || undefined,
    source: a.source,
    meta,
    underlying: [a],
    plainEnglish:
      a.source === "fdd" && a.analytics
        ? describeFaultCause(a.analytics)
        : String(a.detail || symptom || a.title || ""),
    technical:
      ctx && a.source === "fdd"
        ? [
            ctx.equipment?.id ? `Equipment: ${ctx.equipment.id}` : "",
            ctx.rule_id ? `Rule: ${ctx.rule_id}` : "",
            ctx.point?.id ? `Point id: ${ctx.point.id}` : "",
          ]
            .filter(Boolean)
            .join(" · ")
        : a.analytics
          ? JSON.stringify(a.analytics, null, 2)
          : [a.rule_id, a.rule_name].filter(Boolean).join(" · ") || undefined,
    modelContext: ctx,
  };
}

const SEVERITY_ORDER: Record<DisplayFault["severity"], number> = {
  critical: 0,
  high: 1,
  medium: 2,
  info: 3,
};

export function buildDisplayFaults(families: FaultFamily[]): DisplayFault[] {
  const flat = flattenFamilies(families);
  const used = new Set<string>();
  const cards: DisplayFault[] = [];

  const historian = groupHistorianLag(flat);
  if (historian) {
    cards.push(historian);
    flat.filter(isHistorianLag).forEach((a) => used.add(String(a.id || a.title)));
  }

  const fddInput = groupFddInput(flat);
  if (fddInput) {
    cards.push(fddInput);
    flat.filter(isModelFddInput).forEach((a) => used.add(String(a.id || a.title)));
  }

  const overrides = groupBacnetOverrides(flat);
  if (overrides) {
    cards.push(overrides);
    flat.filter(isBacnetOperatorOverride).forEach((a) => used.add(String(a.id || a.title)));
  }

  for (const fam of families) {
    const eqLabel = fam.label;
    for (const a of fam.faults) {
      const key = String(a.id || a.title);
      if (used.has(key)) continue;
      if (isHistorianLag(a) || isModelFddInput(a) || isBacnetOperatorOverride(a)) continue;
      const eqFromAlert = String(a.equipment_name || "").trim();
      cards.push(alertToDisplay(a, eqFromAlert || eqLabel));
    }
  }

  return cards.sort(
    (a, b) =>
      SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] ||
      a.title.localeCompare(b.title),
  );
}

export function countBySeverity(cards: DisplayFault[]) {
  return {
    critical: cards.filter((c) => c.severity === "critical").length,
    high: cards.filter((c) => c.severity === "high").length,
    medium: cards.filter((c) => c.severity === "medium").length,
    total: cards.length,
  };
}

/** Stable backend ids for BAS-style alarm clear/ack. */
export function faultAlertIds(fault: DisplayFault): string[] {
  const ids = fault.underlying.map((u) => String(u.id || "").trim()).filter(Boolean);
  if (ids.length) return ids;
  return [fault.id];
}
