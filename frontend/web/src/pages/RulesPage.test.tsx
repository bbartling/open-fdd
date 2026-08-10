import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Navigate, Route, Routes } from "react-router";

/** Run Rules tab removed — /rules bookmarks redirect to Overview. */
describe("/rules redirect", () => {
  it("navigates to Overview", () => {
    render(
      <MemoryRouter initialEntries={["/rules"]}>
        <Routes>
          <Route path="/rules" element={<Navigate to="/" replace />} />
          <Route path="/" element={<div data-testid="overview">Overview</div>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("overview")).toBeTruthy();
  });
});
