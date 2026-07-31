import { describe, expect, it } from "vitest";
import { parseErrorEnvelope } from "./client";

describe("parseErrorEnvelope", () => {
  it("parses a valid error envelope", () => {
    const body = JSON.stringify({
      error: {
        code: "mapping.role_missing",
        message: "SAT role not mapped",
        details: { role: "SAT" },
        retryable: false,
        request_id: "req-abc",
      },
    });

    const envelope = parseErrorEnvelope(body);
    expect(envelope).not.toBeNull();
    expect(envelope?.error.code).toBe("mapping.role_missing");
    expect(envelope?.error.message).toBe("SAT role not mapped");
    expect(envelope?.error.retryable).toBe(false);
    expect(envelope?.error.request_id).toBe("req-abc");
  });

  it("returns null for non-envelope JSON", () => {
    expect(parseErrorEnvelope(JSON.stringify({ ok: true }))).toBeNull();
  });

  it("returns null for invalid JSON", () => {
    expect(parseErrorEnvelope("not json")).toBeNull();
  });

  it("returns null when error object lacks required fields", () => {
    expect(
      parseErrorEnvelope(JSON.stringify({ error: { code: "only_code" } })),
    ).toBeNull();
  });
});
