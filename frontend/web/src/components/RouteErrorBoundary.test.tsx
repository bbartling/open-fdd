import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { RouteErrorBoundary } from "./RouteErrorBoundary";

function Boom(): never {
  throw new Error("plot failed");
}

describe("RouteErrorBoundary", () => {
  it("renders children until a child throws", () => {
    render(
      <RouteErrorBoundary>
        <p>Overview</p>
      </RouteErrorBoundary>,
    );
    expect(screen.getByText("Overview")).toBeTruthy();
  });

  it("shows a reload alert instead of blanking the router", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <RouteErrorBoundary>
        <Boom />
      </RouteErrorBoundary>,
    );
    expect(screen.getByTestId("route-error").textContent).toMatch(/Reload/);
    vi.restoreAllMocks();
  });
});
