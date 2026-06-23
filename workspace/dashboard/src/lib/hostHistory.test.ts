import { describe, expect, it } from "vitest";
import { appendHostHistory, HOST_HISTORY_MS } from "./hostHistory";

describe("appendHostHistory", () => {
  it("drops samples older than one hour", () => {
    const now = Date.parse("2026-05-30T12:00:00Z");
    const old = { at: "2026-05-30T10:00:00Z", cpu: 10, mem: 20 };
    const recent = { at: "2026-05-30T11:55:00Z", cpu: 30, mem: 40 };
    const next = appendHostHistory([old], recent, now);
    expect(next).toEqual([recent]);
  });

  it("keeps chronological order within the window", () => {
    const now = Date.parse("2026-05-30T12:00:00Z");
    const a = { at: "2026-05-30T11:50:00Z", cpu: 1, mem: 2 };
    const b = { at: "2026-05-30T11:55:00Z", cpu: 3, mem: 4 };
    expect(appendHostHistory([], a, now)).toEqual([a]);
    expect(appendHostHistory([a], b, now)).toEqual([a, b]);
    expect(HOST_HISTORY_MS).toBe(3_600_000);
  });
});
