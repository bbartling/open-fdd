import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { AuthPage } from "./AuthPage";

vi.mock("../api/authApi", () => ({
  getAuthStatus: vi.fn(async () => ({ ok: true, auth_required: true })),
  getAuthMe: vi.fn(async () => {
    throw new Error("unauthorized");
  }),
  login: vi.fn(async () => ({
    ok: true,
    token: "jwt",
    access_token: "jwt",
    token_type: "Bearer",
    role: "admin",
    subject: "admin",
  })),
  logout: vi.fn(),
}));

import { getAuthMe, login } from "../api/authApi";

describe("AuthPage", () => {
  beforeEach(() => {
    vi.mocked(login).mockClear();
    vi.mocked(getAuthMe).mockRejectedValue(new Error("unauthorized"));
  });

  it("renders oracle sign-in and navigates home after login", async () => {
    render(
      <MemoryRouter initialEntries={["/auth"]}>
        <Routes>
          <Route path="/auth" element={<AuthPage />} />
          <Route path="/" element={<div data-testid="home">home</div>} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("auth-required").textContent).toContain("true");
      expect(screen.getByTestId("auth-user").textContent).toContain("—");
    });

    fireEvent.change(screen.getByTestId("auth-password"), {
      target: { value: "secret" },
    });
    fireEvent.click(screen.getByTestId("auth-login"));

    await waitFor(() => {
      expect(login).toHaveBeenCalledWith("admin", "secret");
      expect(screen.getByTestId("home")).toBeTruthy();
    });
  });
});
