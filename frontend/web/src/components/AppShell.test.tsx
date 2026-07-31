import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { AppShell } from "./AppShell";
import { MAIN_SECTIONS } from "../nav/sections";

describe("AppShell layout parity", () => {
  it("renders Streamlit section order and brand", () => {
    render(
      <MemoryRouter>
        <AppShell title="Home" caption="Parity shell">
          <div>body</div>
        </AppShell>
      </MemoryRouter>,
    );

    expect(screen.getByText("Open-FDD")).toBeTruthy();
    expect(screen.getByTestId("page-caption").textContent).toBe("Parity shell");

    const tabs = screen.getByTestId("section-tabs");
    const labels = [...tabs.querySelectorAll("[data-section]")].map(
      (el) => el.getAttribute("data-section"),
    );
    expect(labels).toEqual(MAIN_SECTIONS.map((s) => s.id));
  });

  it("collapses the sidebar when toggle is pressed", () => {
    render(
      <MemoryRouter>
        <AppShell title="Jobs">
          <div>body</div>
        </AppShell>
      </MemoryRouter>,
    );

    const shell = screen.getByTestId("app-shell");
    expect(shell.getAttribute("data-sidebar-collapsed")).toBe("false");
    fireEvent.click(screen.getByTestId("sidebar-collapse"));
    expect(shell.getAttribute("data-sidebar-collapsed")).toBe("true");
  });
});
