import { describe, expect, it } from "vitest";
import { classifyOpenfddTaskPreview } from "./openfdd-agent-route-preview";

describe("classifyOpenfddTaskPreview", () => {
  it.each([
    ["GET /health", "simple", "health check"],
    ["list sites via api", "simple", "list sites"],
    ["single csv upload check", "simple", "single artifact"],
    ["quick check logs", "simple", "explicitly trivial"],
    ["http probe returns 504 timeout", "simple", "HTTP status / timeout"],
    ["ambiguous root cause spans multiple subservices here", "complex", "ambiguous + multi-component-ish"],
    ["security vulnerability in auth path", "complex", "security"],
    ["BRICK ttl import merge refactor", "complex", "BRICK redesign"],
    ["redesign ingest pipeline architecture broadly", "complex", "ingest architecture"],
    ["timing-dependent race condition on BACnet driver", "complex", "race / timing-dependent"],
    ["hello can you summarize open-fdd", "simple", "default tier plain text"],
  ])('classifies %j as %s (%s)', (text, expected, _why) => {
    expect(classifyOpenfddTaskPreview(text)).toBe(expected);
  });

  it("uses default tier when text is whitespace-only", () => {
    expect(classifyOpenfddTaskPreview("   ")).toBe("simple");
    expect(classifyOpenfddTaskPreview("", "complex")).toBe("complex");
  });

  it("prefers COMPLEX when both COMPLEX and SIMPLE patterns match", () => {
    expect(classifyOpenfddTaskPreview("security issue but just a trivial one liner check")).toBe("complex");
  });
});
