import { describe, expect, it, vi } from "vitest";
import { newRequestId } from "./requestId";

describe("newRequestId", () => {
  it("returns a non-empty id when randomUUID is available", () => {
    const id = newRequestId();
    expect(id.length).toBeGreaterThan(8);
  });

  it("falls back when randomUUID is missing (LAN HTTP)", () => {
    const real = globalThis.crypto;
    vi.stubGlobal("crypto", {
      getRandomValues: real.getRandomValues.bind(real),
      // no randomUUID — mirrors http://192.168.x.x secure-context rules
    });
    try {
      const id = newRequestId();
      expect(id).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
      );
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
