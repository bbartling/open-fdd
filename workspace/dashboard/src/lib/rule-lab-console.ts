/** Format playground test-rule events for the Rule Lab console. */

export type RuleTestEvent = {
  type?: string;
  text?: string;
  trace?: string;
  row?: number;
  ts?: string;
  status?: string;
  message?: string;
  rows?: number;
  flagged?: number;
  sweep_mode?: string;
};

export type LintIssue = {
  line?: number;
  col?: number;
  message: string;
  severity: string;
};

export function formatLintIssues(issues: LintIssue[]): string {
  if (!issues.length) return "Lint OK — no issues.";
  return issues
    .map((i) => `${i.severity} line ${i.line ?? "?"} col ${i.col ?? "?"}: ${i.message}`)
    .join("\n");
}

export function formatRuleTestEvents(events: RuleTestEvent[], opts?: { maxLines?: number }): string {
  const max = opts?.maxLines ?? 400;
  const lines: string[] = [];
  let n = 0;

  const push = (line: string, kind?: "error" | "warn") => {
    if (n >= max) return;
    lines.push(kind ? `[${kind}] ${line}` : line);
    n += 1;
  };

  for (const evt of events) {
    if (n >= max) break;
    const t = evt.type || "";
    if (t === "stdout" || t === "error") {
      const text = (evt.text || "").replace(/\r\n/g, "\n");
      for (const part of text.split("\n")) {
        push(part, t === "error" ? "error" : undefined);
      }
      if (evt.trace) {
        for (const part of evt.trace.split("\n")) {
          push(part, "error");
        }
      }
      continue;
    }
    if (t === "row") {
      if (evt.status === "fault" || evt.status === "error") {
        const msg = evt.status === "error" ? ` ERROR ${evt.message || ""}` : " FAULT";
        push(`row ${evt.row ?? "?"}  ${evt.ts ?? ""}${msg}`);
      }
      continue;
    }
    if (t === "summary") {
      push(
        `--- sweep: ${evt.flagged ?? 0} flagged / ${evt.rows ?? 0} rows (mode=${evt.sweep_mode || "per_row"}) ---`,
      );
    }
  }

  if (events.length > max) {
    lines.push(`… (${events.length - max} more events omitted)`);
  }
  return lines.join("\n");
}

export function formatBatchSummary(body: {
  rules_run?: number;
  site_runs?: number;
  flagged_runs?: number;
  error_runs?: number;
  ms?: number;
  lookback_hours?: number | null;
  runs?: { rule_name?: string; site_id?: string; flagged?: number; status?: string; error?: string; rows?: number }[];
}): string {
  const lines = [
    ">>> Update all records — batch complete",
    `rules=${body.rules_run ?? 0} site_runs=${body.site_runs ?? 0} flagged_runs=${body.flagged_runs ?? 0} errors=${body.error_runs ?? 0} (${body.ms ?? 0} ms)`,
  ];
  if (body.lookback_hours != null) {
    lines.push(`lookback: ${body.lookback_hours}h`);
  }
  for (const run of body.runs || []) {
    const err = run.status === "error" ? ` ERROR ${run.error || ""}` : "";
    lines.push(`  ${run.rule_name || "?"} @ ${run.site_id}: flagged=${run.flagged ?? 0}/${run.rows ?? 0}${err}`);
  }
  return lines.join("\n");
}
