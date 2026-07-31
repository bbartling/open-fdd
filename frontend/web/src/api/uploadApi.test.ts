import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { buildPackageUploadFormData, uploadPackage } from "./uploadApi";

describe("uploadApi", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        return new Response(JSON.stringify({ ok: true, building_id: "B1" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("builds multipart form data", () => {
    const file = new File(["PK"], "pkg.zip", { type: "application/zip" });
    const form = buildPackageUploadFormData(file);
    expect(form.get("file")).toBeTruthy();
  });

  it("posts multipart zip and returns body", async () => {
    const file = new File(["PK"], "pkg.zip", { type: "application/zip" });
    const result = await uploadPackage(file);
    expect(result.ok).toBe(true);
    expect(result.building_id).toBe("B1");
    expect(fetch).toHaveBeenCalled();
    const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
  });

  it("throws ApiClientError when package import is rejected", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        return new Response(
          JSON.stringify({
            ok: false,
            error: "path traversal rejected: \"../evil\"",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }),
    );
    const file = new File(["PK"], "bad.zip", { type: "application/zip" });
    await expect(uploadPackage(file)).rejects.toThrow(/path traversal rejected/);
  });
});
