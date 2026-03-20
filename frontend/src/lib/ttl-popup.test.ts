import { describe, expect, test, vi } from "vitest";
import { writeTtlToPopup } from "@/lib/ttl-popup";

describe("ttl-popup", () => {
  test("writes escaped TTL content into popup document", () => {
    const write = vi.fn();
    const close = vi.fn();
    writeTtlToPopup(
      {
        document: { write, close },
      },
      "<urn:test> <urn:p> \"a & b\" .",
    );
    expect(write).toHaveBeenCalledTimes(1);
    const html = String(write.mock.calls[0][0]);
    expect(html).toContain("&lt;urn:test&gt;");
    expect(html).toContain("&amp;");
    expect(close).toHaveBeenCalledTimes(1);
  });
});

