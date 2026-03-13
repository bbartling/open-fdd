import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { timeAgo, severityVariant } from "./utils";

describe("timeAgo", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2025-03-04T12:00:00Z"));
  });
  afterEach(() => vi.useRealTimers());

  it("returns 'just now' for recent time", () => {
    expect(timeAgo("2025-03-04T11:59:50Z")).toBe("just now");
  });
  it("returns 'Xm ago' for minutes", () => {
    expect(timeAgo("2025-03-04T11:55:00Z")).toBe("5m ago");
  });
  it("returns 'Xh ago' for hours", () => {
    expect(timeAgo("2025-03-04T10:00:00Z")).toBe("2h ago");
  });
  it("returns 'Xd ago' for days", () => {
    expect(timeAgo("2025-03-02T12:00:00Z")).toBe("2d ago");
  });
  it("returns locale date for older", () => {
    expect(timeAgo("2025-02-01T12:00:00Z")).toMatch(/Feb|2\/1|01\.02/);
  });
});

describe("severityVariant", () => {
  it("returns destructive for critical/error", () => {
    expect(severityVariant("critical")).toBe("destructive");
    expect(severityVariant("error")).toBe("destructive");
  });
  it("returns outline for warning", () => {
    expect(severityVariant("warning")).toBe("outline");
  });
  it("returns secondary for other", () => {
    expect(severityVariant("info")).toBe("secondary");
    expect(severityVariant("")).toBe("secondary");
  });
});
