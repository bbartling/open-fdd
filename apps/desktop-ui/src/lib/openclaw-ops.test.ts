import { describe, expect, it } from "vitest";
import {
  buildCronAddCommand,
  buildCronCleanupCommand,
  buildMemoryCleanupCommands,
  buildSkillsRefreshCommands,
  validateCronExpression,
} from "./openclaw-ops";

describe("openclaw ops command builders", () => {
  it("builds isolated cron command with announce and message", () => {
    const cmd = buildCronAddCommand({
      name: "Morning Sweep",
      schedule: "0 7 * * *",
      tz: "America/Chicago",
      message: "Summarize overnight FDD issues",
      session: "isolated",
      failureDestination: "ops-alerts",
      alertOnSkipped: true,
      idempotencyKey: "site-sweep-v1",
      reconcileTag: "portfolio-a",
      correlationIdPrefix: "ofdd",
    });
    expect(cmd).toContain("openclaw cron add");
    expect(cmd).toContain('--session isolated');
    expect(cmd).toContain('--announce');
    expect(cmd).toContain("--message 'Summarize overnight FDD issues'");
    expect(cmd).toContain("--failure-destination 'ops-alerts'");
    expect(cmd).toContain("--alert-on-skipped");
    expect(cmd).toContain("--idempotency-key 'site-sweep-v1'");
    expect(cmd).toContain("--reconcile-tag 'portfolio-a'");
    expect(cmd).toContain("--correlation-prefix 'ofdd'");
  });

  it("builds powershell style line continuation", () => {
    const cmd = buildCronAddCommand(
      {
        name: "Morning Sweep",
        schedule: "0 7 * * *",
        tz: "America/Chicago",
        message: "Summarize overnight FDD issues",
        session: "isolated",
        failureDestination: "ops-alerts",
        alertOnSkipped: true,
        idempotencyKey: "site-sweep-v1",
        reconcileTag: "portfolio-a",
        correlationIdPrefix: "ofdd",
      },
      "powershell",
    );
    expect(cmd).toContain(" `\n  --name");
  });

  it("builds main-session cron command with system-event and wake", () => {
    const cmd = buildCronAddCommand({
      name: "Reminder",
      schedule: "*/30 * * * *",
      tz: "UTC",
      message: "check status",
      session: "main",
      failureDestination: "ops-alerts",
      alertOnSkipped: true,
      idempotencyKey: "check-status-v1",
      reconcileTag: "portfolio-main",
      correlationIdPrefix: "ofdd",
    });
    expect(cmd).toContain('--session main');
    expect(cmd).toContain("--system-event 'check status'");
    expect(cmd).toContain('--wake now');
  });

  it("escapes single quotes for posix and powershell", () => {
    const posix = buildCronAddCommand(
      {
        name: "Plant A",
        schedule: "0 7 * * *",
        tz: "UTC",
        message: "check O'Brien AHU",
        session: "isolated",
        failureDestination: "ops-alerts",
        alertOnSkipped: true,
        idempotencyKey: "plant-a-v1",
        reconcileTag: "plant-a",
        correlationIdPrefix: "ofdd",
      },
      "posix",
    );
    expect(posix).toContain("--message 'check O'\"'\"'Brien AHU'");

    const pwsh = buildCronAddCommand(
      {
        name: "Plant A",
        schedule: "0 7 * * *",
        tz: "UTC",
        message: "check O'Brien AHU",
        session: "isolated",
        failureDestination: "ops-alerts",
        alertOnSkipped: true,
        idempotencyKey: "plant-a-v1",
        reconcileTag: "plant-a",
        correlationIdPrefix: "ofdd",
      },
      "powershell",
    );
    expect(pwsh).toContain("--message 'check O''Brien AHU'");
  });

  it("includes cleanup snippets", () => {
    expect(buildCronCleanupCommand()).toContain("openclaw cron remove <job-id>");
    expect(buildMemoryCleanupCommands("posix")).toContain("truncate -s 0");
    expect(buildMemoryCleanupCommands("powershell")).toContain("Set-Content");
    expect(buildSkillsRefreshCommands()).toContain("openclaw skills update --all");
  });

  it("validates cron expression with hints", () => {
    const bad = validateCronExpression("* * *");
    expect(bad.valid).toBe(false);
    expect(bad.hints[0]).toMatch(/5 fields/i);

    const good = validateCronExpression("0 */6 * * *");
    expect(good.valid).toBe(true);
    expect(good.hints.join(" ")).toMatch(/5-field cron/i);

    const everyMinute = validateCronExpression("* * * * *");
    expect(everyMinute.valid).toBe(true);
    expect(everyMinute.hints.join(" ")).toMatch(/skipped runs/i);
  });
});

