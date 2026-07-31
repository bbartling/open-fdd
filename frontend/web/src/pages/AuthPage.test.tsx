import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { AuthPage } from "./AuthPage";

vi.mock("../api/authApi", () => ({
  getAuthStatus: vi.fn(async () => ({ ok: true, auth_required: false })),
  getAuthMe: vi.fn(async () => ({
    ok: true,
    username: "dev",
    role: "admin",
    auth_required: false,
  })),
  login: vi.fn(async () => ({
    ok: true,
    token: "open",
    access_token: "open",
    token_type: "Bearer",
    role: "admin",
    subject: "dev",
  })),
  logout: vi.fn(),
}));

import { login } from "../api/authApi";

describe("AuthPage", () => {
  beforeEach(() => {
    vi.mocked(login).mockClear();
  });

  it("shows status and logs in", async () => {
    render(
      <MemoryRouter>
        <AuthPage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("auth-required").textContent).toContain("false");
      expect(screen.getByTestId("auth-user").textContent).toContain("dev");
    });
    fireEvent.click(screen.getByTestId("auth-login").querySelector("button")!);
    await waitFor(() => {
      expect(login).toHaveBeenCalled();
      expect(screen.getByTestId("auth-notice").textContent).toMatch(/Logged in/);
    });
  });
});
