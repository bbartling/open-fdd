export type CronDraft = {
  name: string;
  schedule: string;
  tz: string;
  message: string;
  session: "isolated" | "main";
  failureDestination: string;
  alertOnSkipped: boolean;
  idempotencyKey: string;
  reconcileTag: string;
  correlationIdPrefix: string;
};

export type ShellFlavor = "posix" | "powershell";
export type CronValidation = {
  valid: boolean;
  hints: string[];
};

function quote(value: string, shell: ShellFlavor): string {
  if (shell === "powershell") {
    return `'${String(value).replaceAll("'", "''")}'`;
  }
  // POSIX single-quote escaping: 'foo'"'"'bar'
  return `'${String(value).replaceAll("'", `'\"'\"'`)}'`;
}

export function buildCronAddCommand(draft: CronDraft, shell: ShellFlavor = "posix"): string {
  const effectiveSession: CronDraft["session"] = draft.session || "isolated";
  const effectiveMessage = draft.message || (
    effectiveSession === "isolated"
      ? "Run Open-FDD health + FDD checks for all active sites."
      : "Run Open-FDD reminder task."
  );
  const pieces = [
    "openclaw cron add",
    `--name ${quote(draft.name || "Open-FDD task", shell)}`,
    `--cron ${quote(draft.schedule || "0 */6 * * *", shell)}`,
    `--tz ${quote(draft.tz || "UTC", shell)}`,
    `--session ${effectiveSession}`,
  ];
  if (effectiveSession === "isolated") {
    pieces.push(
      `--message ${quote(effectiveMessage, shell)}`,
    );
    pieces.push("--announce");
  } else {
    pieces.push(`--system-event ${quote(effectiveMessage, shell)}`);
    pieces.push("--wake now");
  }
  if ((draft.failureDestination || "").trim()) {
    pieces.push(`--failure-destination ${quote(draft.failureDestination, shell)}`);
  }
  if (draft.alertOnSkipped) {
    pieces.push("--alert-on-skipped");
  }
  if ((draft.idempotencyKey || "").trim()) {
    pieces.push(`--idempotency-key ${quote(draft.idempotencyKey, shell)}`);
  }
  if ((draft.reconcileTag || "").trim()) {
    pieces.push(`--reconcile-tag ${quote(draft.reconcileTag, shell)}`);
  }
  if ((draft.correlationIdPrefix || "").trim()) {
    pieces.push(`--correlation-prefix ${quote(draft.correlationIdPrefix, shell)}`);
  }
  if (shell === "powershell") {
    return pieces.join(" `\n  ");
  }
  return pieces.join(" \\\n  ");
}

export function buildCronCleanupCommand(): string {
  return [
    "openclaw cron list",
    "# reconcile last executions for drift/skip visibility:",
    "openclaw cron runs --recent 20",
    "# remove one:",
    "openclaw cron remove <job-id>",
  ].join("\n");
}

export function buildMemoryCleanupCommands(shell: ShellFlavor = "posix"): string {
  if (shell === "powershell") {
    return [
      "Set-Content \"$HOME/.openclaw/workspace/MEMORY.md\" -Value \"\"",
      "Remove-Item \"$HOME/.openclaw/workspace/memory/*.md\" -ErrorAction SilentlyContinue",
    ].join("\n");
  }
  return [
    "truncate -s 0 ~/.openclaw/workspace/MEMORY.md",
    "rm -f ~/.openclaw/workspace/memory/*.md",
  ].join("\n");
}

export function buildSkillsRefreshCommands(): string {
  return [
    "openclaw skills list --eligible",
    "openclaw skills update --all",
    "# optional clean reinstall path",
    "# rm -rf ~/.openclaw/workspace/skills/<skill-name>",
    "# openclaw skills install <skill-slug>",
  ].join("\n");
}

export function validateCronExpression(input: string): CronValidation {
  const expr = String(input || "").trim();
  if (!expr) {
    return { valid: false, hints: ["Cron expression is required."] };
  }
  if (expr.startsWith("@")) {
    const ok = new Set([
      "@yearly",
      "@annually",
      "@monthly",
      "@weekly",
      "@daily",
      "@hourly",
      "@reboot",
    ]);
    if (!ok.has(expr.toLowerCase())) {
      return { valid: false, hints: ["Unknown shorthand. Try @hourly, @daily, or a 5-field cron."] };
    }
    return { valid: true, hints: ["Shorthand schedule detected."] };
  }

  const fields = expr.split(/\s+/).filter(Boolean);
  if (fields.length !== 5 && fields.length !== 6) {
    return { valid: false, hints: ["Use 5 fields (or 6 fields with seconds)."] };
  }

  const allowed = /^[\d*/,\-?A-Za-z#L]+$/;
  const bad = fields.find((f) => !allowed.test(f));
  if (bad) {
    return { valid: false, hints: [`Invalid token '${bad}'. Use digits, *, /, -, commas, ?, names.`] };
  }

  const hints: string[] = [];
  if (fields.length === 5) {
    hints.push("5-field cron: minute hour day month weekday.");
  } else {
    hints.push("6-field cron: seconds minute hour day month weekday.");
  }
  if (fields[2] === "*" && fields[1] === "*" && fields[0].includes("*/")) {
    hints.push("High frequency detected; confirm this won't overload your gateway.");
  }
  if (fields[0] === "*" && fields[1] === "*") {
    hints.push(
      fields.length === 6
        ? "Every-second cadence can generate skipped runs if execution lasts >1s."
        : "Every-minute cadence can generate skipped runs if execution lasts >60s.",
    );
  }
  return { valid: true, hints };
}

