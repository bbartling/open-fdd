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

  it("gets generation status", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      generation: "streamlit",
      source: "default",
      default_generation: "streamlit",
      production_default_flipped: false,
      sticky_cookie: "openfdd_ui_generation",
    });
    const st = await getUiGeneration();
    expect(st.production_default_flipped).toBe(false);
    expect(st.generation).toBe("streamlit");
  });

  it("puts generation without flipping production default", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      generation: "react",
      production_default_flipped: false,
    });
    const out = await setUiGeneration("react", "canary cohort");
    expect(apiFetch).toHaveBeenCalledWith(
      "/api/ui/generation",
      expect.objectContaining({ method: "PUT" }),
    );
    expect(out.production_default_flipped).toBe(false);
  });
});
