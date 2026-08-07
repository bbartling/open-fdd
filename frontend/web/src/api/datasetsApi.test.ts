import { afterEach, describe, expect, it, vi } from "vitest";
import { deleteDataset } from "./datasetsApi";

describe("deleteDataset", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("DELETEs /api/datasets?id=", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ ok: true, action_id: "act-1" }),
      text: async () => "",
    }));
    vi.stubGlobal("fetch", fetchMock);

    const body = await deleteDataset("BUILDING_100");
    expect(body).toEqual({ ok: true, action_id: "act-1" });
    expect(fetchMock).toHaveBeenCalledOnce();
    const call = fetchMock.mock.calls[0];
    expect(call).toBeDefined();
    const url = String(call?.[0] ?? "");
    const init = (call?.[1] ?? {}) as RequestInit;
    expect(url).toContain("/api/datasets?id=BUILDING_100");
    expect(init.method).toBe("DELETE");
  });
});
