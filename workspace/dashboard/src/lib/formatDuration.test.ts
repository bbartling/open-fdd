import { describe, expect, it } from "vitest";
import { formatDurationMs } from "./formatDuration";

describe("formatDurationMs", () => {
  it("formats sub-minute and minute ranges", () => {
    expect(formatDurationMs(450)).toBe("450ms");
    expect(formatDurationMs(12_000)).toBe("12s");
    expect(formatDurationMs(135_000)).toBe("2m 15s");
    expect(formatDurationMs(724_000)).toBe("12m 4s");
  });
});
