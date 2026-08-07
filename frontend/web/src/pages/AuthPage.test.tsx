import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { AuthPage } from "./AuthPage";

vi.mock("../api/authApi", () => ({
  getAuthMe: vi.fn(async () => {
    throw new Error("unauthorized");
  }),
  getStoredToken: vi.fn(() => null),
  setStoredToken: vi.fn(),
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

import { getAuthMe, getStoredToken, login, setStoredToken } from "../api/authApi";

describe("AuthPage", () => {
  beforeEach(() => {
    vi.mocked(login).mockClear();
    vi.mocked(setStoredToken).mockClear();
    vi.mocked(getStoredToken).mockReturnValue(null);
    vi.mocked(getAuthMe).mockRejectedValue(new Error("unauthorized"));
  });

  it("renders a clean sign-in form and navigates home after login", async () => {
    vi.mocked(login).mockImplementation(async () => {
      vi.mocked(getStoredToken).mockReturnValue("jwt");
      return {
        ok: true,
        token: "jwt",
        access_token: "jwt",
        token_type: "Bearer",
        role: "admin",
        subject: "admin",
      };
    });
    vi.mocked(getAuthMe).mockResolvedValue({
      ok: true,
      username: "admin",
      role: "admin",
      auth_required: true,
    });

    render(
      <MemoryRouter initialEntries={["/auth"]}>
        <Routes>
          <Route path="/auth" element={<AuthPage />} />
          <Route path="/" element={<div data-testid="home">home</div>} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByTestId("auth-page")).toBeTruthy();
    expect(screen.queryByText(/bootstrap_credentials/i)).toBeNull();
    expect(screen.queryByText(/Auth required/i)).toBeNull();
    expect(screen.queryByText(/Bench password/i)).toBeNull();

    fireEvent.change(screen.getByTestId("auth-username"), {
      target: { value: "admin" },
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

  it("does not claim an open-mode session without a browser token", async () => {
    vi.mocked(getAuthMe).mockResolvedValue({
      ok: true,
      username: "dev",
      role: "admin",
      auth_required: false,
    });
    vi.mocked(getStoredToken).mockReturnValue(null);

    render(
      <MemoryRouter initialEntries={["/auth"]}>
        <Routes>
          <Route path="/auth" element={<AuthPage />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("auth-login")).toBeTruthy();
    });
    expect(screen.queryByTestId("auth-continue")).toBeNull();
    expect(screen.queryByText(/active session/i)).toBeNull();
  });
});
