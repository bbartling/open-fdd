import { describe, expect, it, vi, beforeEach } from "vitest";
import {
  getStoredActiveTenant,
  selectTenant,
  setStoredActiveTenant,
} from "./tenantApi";

vi.mock("./client", () => ({
  apiFetch: vi.fn(),
}));
vi.mock("./authApi", () => ({
  setStoredToken: vi.fn(),
}));

import { apiFetch } from "./client";
import { setStoredToken } from "./authApi";

describe("tenantApi", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.mocked(apiFetch).mockReset();
    vi.mocked(setStoredToken).mockReset();
  });

  it("stores active tenant locally", () => {
    setStoredActiveTenant("legacy");
    expect(getStoredActiveTenant()).toBe("legacy");
    setStoredActiveTenant(null);
    expect(getStoredActiveTenant()).toBeNull();
  });

  it("selectTenant stores legacy and does not rotate token when OFF", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      multi_tenant: false,
      active_tenant_id: "legacy",
      token: null,
      access_token: null,
    });
    const res = await selectTenant("legacy");
    expect(res.active_tenant_id).toBe("legacy");
    expect(getStoredActiveTenant()).toBe("legacy");
    expect(setStoredToken).not.toHaveBeenCalled();
  });
});
