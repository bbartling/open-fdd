import { afterEach, describe, expect, it, vi } from "vitest";
import { copyToClipboard } from "./clipboard";

describe("copyToClipboard", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses execCommand fallback when clipboard API is missing", async () => {
    const textarea = {
      value: "",
      select: vi.fn(),
      setSelectionRange: vi.fn(),
      focus: vi.fn(),
      setAttribute: vi.fn(),
      style: {} as CSSStyleDeclaration,
    };
    vi.stubGlobal("navigator", {});
    const exec = vi.fn(() => true);
    vi.stubGlobal("document", {
      createElement: vi.fn(() => textarea),
      body: { appendChild: vi.fn(), removeChild: vi.fn() },
      execCommand: exec,
    });

    await copyToClipboard("hello bundle");
    expect(textarea.value).toBe("hello bundle");
    expect(exec).toHaveBeenCalledWith("copy");
  });
});
