import { afterEach, describe, expect, it, vi } from "vitest";
import { deleteDataset } from "./datasetsApi";

describe("deleteDataset", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("DELETEs /api/datasets?id=", async () => {
    let seenUrl = "";
    let seenMethod = "";
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        seenUrl = String(input);
        seenMethod = String(init?.method ?? "GET");
        return {
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({ ok: true, action_id: "act-1" }),
          text: async () => "",
        };
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    const body = await deleteDataset("BUILDING_100");
    expect(body).toEqual({ ok: true, action_id: "act-1" });
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(seenUrl).toContain("/api/datasets?id=BUILDING_100");
    expect(seenMethod).toBe("DELETE");
  });
});
