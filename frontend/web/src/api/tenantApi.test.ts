import { describe, expect, it, vi, beforeEach } from "vitest";
import {
  clearTenantScopedClientState,
  getStoredActiveTenant,
  selectTenant,
  setStoredActiveTenant,
  TENANT_CHANGED_EVENT,
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
    localStorage.clear();
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

  it("clears tenant-scoped drafts without dropping the session", () => {
    sessionStorage.setItem("openfdd.auth.token", "keep");
    sessionStorage.setItem("openfdd.tenant.active", "tenant_a");
    sessionStorage.setItem("openfdd.formDraft.lab", "{}");
    localStorage.setItem("openfdd.ui.rule_params", "{\"confirm_min\":10}");
    localStorage.setItem("openfdd.ui.rule_params.building=site_a", "{\"confirm_min\":4}");
    const seen: string[] = [];
    const onChanged = () => {
      seen.push(TENANT_CHANGED_EVENT);
    };
    window.addEventListener(TENANT_CHANGED_EVENT, onChanged);
    clearTenantScopedClientState();
    window.removeEventListener(TENANT_CHANGED_EVENT, onChanged);
    expect(sessionStorage.getItem("openfdd.formDraft.lab")).toBeNull();
    expect(localStorage.getItem("openfdd.ui.rule_params")).toBeNull();
    expect(localStorage.getItem("openfdd.ui.rule_params.building=site_a")).toBe(
      "{\"confirm_min\":4}",
    );
    expect(sessionStorage.getItem("openfdd.auth.token")).toBe("keep");
    expect(sessionStorage.getItem("openfdd.tenant.active")).toBe("tenant_a");
    expect(seen).toEqual([TENANT_CHANGED_EVENT]);
  });
});
