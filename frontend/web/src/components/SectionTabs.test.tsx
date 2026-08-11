import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { SectionTabs } from "./SectionTabs";
import { hrefWithSession } from "../session/sessionQuery";

function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="loc">{`${loc.pathname}${loc.search}`}</div>;
}

describe("hrefWithSession", () => {
  it("keeps site and equipment when switching sections", () => {
    expect(hrefWithSession("/rcx", "?site=BUILDING_100&eq=AHU_1")).toBe(
      "/rcx?eq=AHU_1&site=BUILDING_100",
    );
    expect(
      hrefWithSession("/reports?section=fdd-plots", "?site=BUILDING_100&eq=AHU_1"),
    ).toBe("/reports?section=fdd-plots&eq=AHU_1&site=BUILDING_100");
  });
});

describe("SectionTabs site lock", () => {
  it("preserves ?site= when opening FDD Plots", () => {
    render(
      <MemoryRouter initialEntries={["/?site=BUILDING_100&eq=AHU_1"]}>
        <SectionTabs activeSectionId="overview" />
        <Routes>
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByTestId("section-fdd-plots").querySelector("input")!);
    expect(screen.getByTestId("loc").textContent).toContain("site=BUILDING_100");
    expect(screen.getByTestId("loc").textContent).toContain("eq=AHU_1");
    expect(screen.getByTestId("loc").textContent).toContain("/reports");
  });
});
