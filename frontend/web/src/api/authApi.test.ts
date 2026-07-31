import { describe, expect, it, vi, beforeEach } from "vitest";
import { login, setStoredToken, getStoredToken } from "./authApi";

vi.mock("./client", () => ({
  apiFetch: vi.fn(),
}));

import { apiFetch } from "./client";

describe("authApi", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset();
    setStoredToken(null);
  });

  it("stores token on login", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      token: "t1",
      access_token: "t1",
      token_type: "Bearer",
      role: "admin",
      subject: "u1",
    });
    await login("u1", "pw");
    expect(getStoredToken()).toBe("t1");
  });
});
