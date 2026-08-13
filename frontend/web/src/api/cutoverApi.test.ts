import { describe, expect, it, vi, beforeEach } from "vitest";
import { getUiGeneration, setUiGeneration } from "./cutoverApi";

vi.mock("./client", () => ({
  apiFetch: vi.fn(),
}));

import { apiFetch } from "./client";

describe("cutoverApi", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset();
  });

  it("gets generation status after P2-M4 React default", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      generation: "react",
      source: "default",
      default_generation: "react",
      production_default_flipped: true,
      sticky_cookie: "openfdd_ui_generation",
    });
    const st = await getUiGeneration();
    expect(st.production_default_flipped).toBe(true);
    expect(st.generation).toBe("react");
  });

  it("puts generation while production default remains flipped", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      generation: "react",
      production_default_flipped: true,
    });
    const out = await setUiGeneration("react", "cohort pin");
    expect(apiFetch).toHaveBeenCalledWith(
      "/api/ui/generation",
      expect.objectContaining({ method: "PUT" }),
    );
    expect(out.production_default_flipped).toBe(true);
  });

  it("posts migration events", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ok: true });
    const { postMigrationEvent } = await import("./cutoverApi");
    await postMigrationEvent("fallback_click", "user_opt_out", "react");
    expect(apiFetch).toHaveBeenCalledWith(
      "/api/ui/migration-event",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
