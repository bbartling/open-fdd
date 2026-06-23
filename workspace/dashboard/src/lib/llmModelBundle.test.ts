import { describe, expect, it } from "vitest";
import { buildLlmModelBundle } from "./llmModelBundle";

describe("buildLlmModelBundle", () => {
  it("includes prompt and json fence", () => {
    const bundle = buildLlmModelBundle("PROMPT", {
      sites: [{ id: "s1", name: "Site" }],
      equipment: [],
      points: [],
    });
    expect(bundle).toContain("PROMPT");
    expect(bundle).toContain("```json");
    expect(bundle).toContain('"sites"');
  });
});
