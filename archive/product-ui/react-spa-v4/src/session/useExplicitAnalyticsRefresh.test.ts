import { describe, expect, it } from "vitest";
import { renderHook } from "@testing-library/react";
import { useExplicitAnalyticsRefresh } from "./useExplicitAnalyticsRefresh";

describe("useExplicitAnalyticsRefresh", () => {
  it("stays false on open and turns on only for a same-building token bump", () => {
    const hook = renderHook(
      ({ buildingId, refreshToken }) =>
        useExplicitAnalyticsRefresh(buildingId, refreshToken),
      { initialProps: { buildingId: "site-a", refreshToken: 0 } },
    );
    expect(hook.result.current).toBe(false);
    hook.rerender({ buildingId: "site-a", refreshToken: 1 });
    expect(hook.result.current).toBe(true);
    hook.rerender({ buildingId: "site-b", refreshToken: 1 });
    expect(hook.result.current).toBe(false);
  });
});
