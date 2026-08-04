import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { buildPackageUploadFormData, uploadPackage } from "./uploadApi";

describe("uploadApi", () => {
  beforeEach(() => {
    sessionStorage.setItem("openfdd.auth.token", "jwt-test");
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
    sessionStorage.clear();
    vi.unstubAllGlobals();
  });

  it("builds multipart form data", () => {
    const file = new File(["PK"], "pkg.zip", { type: "application/zip" });
    const form = buildPackageUploadFormData(file);
    expect(form.get("file")).toBeTruthy();
  });

  it("posts multipart zip with Bearer token and returns body", async () => {
    const file = new File(["PK"], "pkg.zip", { type: "application/zip" });
    const result = await uploadPackage(file);
    expect(result.ok).toBe(true);
    expect(result.building_id).toBe("B1");
    expect(fetch).toHaveBeenCalled();
    const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect(init.headers.Authorization).toBe("Bearer jwt-test");
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
