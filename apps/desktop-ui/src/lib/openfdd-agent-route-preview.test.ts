import { describe, expect, it } from "vitest";
import { classifyOpenfddTaskPreview } from "./openfdd-agent-route-preview";

describe("classifyOpenfddTaskPreview", () => {
  it("marks health checks as simple", () => {
    expect(classifyOpenfddTaskPreview("GET /health")).toBe("simple");
  });

  it("marks BRICK TTL redesign as complex", () => {
    expect(classifyOpenfddTaskPreview("Refactor BRICK import and TTL merge")).toBe("complex");
  });
});
