import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { AuthGate } from "./AuthGate";

vi.mock("../api/authApi", () => ({
  getAuthStatus: vi.fn(),
  getAuthMe: vi.fn(),
  getStoredToken: vi.fn(),
  logout: vi.fn(),
}));

import {
  getAuthMe,
  getAuthStatus,
  getStoredToken,
} from "../api/authApi";

describe("AuthGate", () => {
  beforeEach(() => {
    vi.mocked(getAuthStatus).mockReset();
    vi.mocked(getAuthMe).mockReset();
    vi.mocked(getStoredToken).mockReset();
  });

  it("redirects to /auth when auth is required and no token", async () => {
    vi.mocked(getAuthStatus).mockResolvedValue({
      ok: true,
      auth_required: true,
    });
    vi.mocked(getStoredToken).mockReturnValue(null);

    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route
            path="/"
            element={
              <AuthGate>
                <div data-testid="secret">secret</div>
              </AuthGate>
            }
          />
          <Route path="/auth" element={<div data-testid="login">login</div>} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("login")).toBeTruthy();
    });
    expect(screen.queryByTestId("secret")).toBeNull();
  });

  it("renders children when auth is not required", async () => {
    vi.mocked(getAuthStatus).mockResolvedValue({
      ok: true,
      auth_required: false,
    });

    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route
            path="/"
            element={
              <AuthGate>
                <div data-testid="secret">secret</div>
              </AuthGate>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("secret")).toBeTruthy();
    });
  });

  it("redirects to /auth for /sites when status probe fails and no token", async () => {
    vi.mocked(getAuthStatus).mockRejectedValue(new Error("central down"));
    vi.mocked(getStoredToken).mockReturnValue(null);

    render(
      <MemoryRouter initialEntries={["/sites"]}>
        <Routes>
          <Route
            path="/sites"
            element={
              <AuthGate>
                <div data-testid="secret">secret</div>
              </AuthGate>
            }
          />
          <Route path="/auth" element={<div data-testid="login">login</div>} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("login")).toBeTruthy();
    });
    expect(screen.queryByTestId("secret")).toBeNull();
  });
});
