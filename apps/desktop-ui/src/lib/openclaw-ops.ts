export type CronDraft = {
  name: string;
  schedule: string;
  tz: string;
  message: string;
  session: "isolated" | "main";
};

export type ShellFlavor = "posix" | "powershell";
export type CronValidation = {
  valid: boolean;
  hints: string[];
};

function quote(value: string): string {
  return `"${value.replaceAll('"', '\\"')}"`;
}

export function buildCronAddCommand(draft: CronDraft, shell: ShellFlavor = "posix"): string {
  const pieces = [
    "openclaw cron add",
    `--name ${quote(draft.name || "Open-FDD task")}`,
    `--cron ${quote(draft.schedule || "0 */6 * * *")}`,
    `--tz ${quote(draft.tz || "UTC")}`,
    `--session ${draft.session || "isolated"}`,
  ];
  if (draft.session === "isolated") {
    pieces.push(`--message ${quote(draft.message || "Run Open-FDD health + FDD checks for all active sites.")}`);
    pieces.push("--announce");
  } else {
    pieces.push(`--system-event ${quote(draft.message || "Run Open-FDD reminder task.")}`);
    pieces.push("--wake now");
  }
  if (shell === "powershell") {
    return pieces.join(" `\n  ");
  }
  return pieces.join(" \\\n  ");
}

export function buildCronCleanupCommand(): string {
  return [
    "openclaw cron list",
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
  return { valid: true, hints };
}

