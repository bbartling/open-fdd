import { describe, expect, it } from "vitest";
import {
  attachLivenessSignal,
  isCentralUnavailable,
  livenessTimeoutMs,
  parseErrorEnvelope,
} from "./client";

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

  it("bounds health and version so a central restart cannot hang the shell", () => {
    expect(livenessTimeoutMs("/api/health")).toBe(8000);
    expect(livenessTimeoutMs("/api/version")).toBe(8000);
    expect(livenessTimeoutMs("/api/auth/status")).toBe(12000);
    expect(livenessTimeoutMs("/api/auth/login")).toBe(20000);
    expect(livenessTimeoutMs("/api/analytics/inspect")).toBeNull();
    const caller = new AbortController().signal;
    expect(attachLivenessSignal("/api/health", { signal: caller }).signal).toBe(
      caller,
    );
    const timed = attachLivenessSignal("/api/health", undefined, 30);
    expect(timed.signal).toBeInstanceOf(AbortSignal);
    expect(timed.signal?.aborted).toBe(false);
  });

  it("treats proxy 503 and abort as central unavailable", () => {
    expect(isCentralUnavailable({ status: 503 })).toBe(true);
    expect(isCentralUnavailable({ status: 404 })).toBe(false);
    expect(isCentralUnavailable(new DOMException("timed out", "AbortError"))).toBe(
      true,
    );
  });

  it("returns null when error object lacks required fields", () => {
    expect(
      parseErrorEnvelope(JSON.stringify({ error: { code: "only_code" } })),
    ).toBeNull();
  });
});
