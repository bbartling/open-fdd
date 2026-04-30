import { describe, expect, it, vi, beforeEach } from "vitest";
import { buildCronApiPreview, createCronJobViaApi } from "./openclaw-gateway";

describe("openclaw gateway API helper", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("posts cron payload to configured endpoint", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        text: async () => '{"ok":true}',
      }),
    );

    const out = await createCronJobViaApi({
      endpointPath: "api/cron/jobs",
      token: "abc",
      payload: {
        name: "Morning Sweep",
        cron: "0 7 * * *",
        tz: "UTC",
        session: "isolated",
        message: "run checks",
      },
    });

    expect(out.ok).toBe(true);
    expect(out.status).toBe(200);
    expect(out.body).toContain('"ok":true');
  });

  it("builds curl preview with endpoint and payload", () => {
    const out = buildCronApiPreview({
      endpointPath: "api/cron/jobs",
      token: "abc",
      payload: {
        name: "Morning Sweep",
        cron: "0 7 * * *",
        tz: "UTC",
        session: "isolated",
        message: "run checks",
      },
    });
    expect(out).toContain("curl -X POST");
    expect(out).toContain("api/cron/jobs");
    expect(out).toContain("Authorization: Bearer abc");
    expect(out).toContain('"name": "Morning Sweep"');
  });
});

