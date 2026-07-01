import { describe, expect, it } from "vitest";

/** Rust edge host stats omit `ollama` under external-agent architecture. */
describe("HostStatsPage API shape", () => {
  it("tolerates missing ollama block", () => {
    const stats = {
      ok: true,
      collected_at: "2026-01-01T00:00:00Z",
      host: { hostname: "edge" },
      cpu: { logical_cores: 4, usage_percent: 12 },
      memory: { percent_used: 40 },
      storage: { available: false },
      network: {},
    };
    expect(stats.ollama?.api_ok).toBeUndefined();
    expect(stats.cpu?.usage_percent).toBe(12);
  });
});
