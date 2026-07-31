import { describe, expect, it } from "vitest";
import { isTerminalRunStatus, pollUntil, nextIntervalMs } from "./asyncOps";
import { ApiClientError } from "./client";

describe("asyncOps", () => {
  it("recognizes terminal run statuses", () => {
    expect(isTerminalRunStatus("SUCCEEDED")).toBe(true);
    expect(isTerminalRunStatus("RUNNING")).toBe(false);
  });

  it("pollUntil resolves when terminal", async () => {
    let n = 0;
    const value = await pollUntil(
      async () => {
        n += 1;
        return { status: n >= 2 ? "SUCCEEDED" : "RUNNING" };
      },
      {
        intervalMs: 1,
        timeoutMs: 1000,
        isTerminal: (v) => isTerminalRunStatus(v.status),
      },
    );
    expect(value.status).toBe("SUCCEEDED");
    expect(n).toBe(2);
  });

  it("pollUntil times out", async () => {
    await expect(
      pollUntil(async () => ({ status: "RUNNING" }), {
        intervalMs: 1,
        timeoutMs: 20,
        isTerminal: (v) => isTerminalRunStatus(v.status),
      }),
    ).rejects.toMatchObject({ code: "async.timeout" });
  });

  it("nextIntervalMs doubles on retryable errors", () => {
    const err = new ApiClientError("busy", {
      code: "busy",
      retryable: true,
      requestId: "r",
      status: 503,
    });
    expect(nextIntervalMs(err, 500)).toBe(1000);
    expect(nextIntervalMs(new Error("x"), 500)).toBe(500);
  });
});
