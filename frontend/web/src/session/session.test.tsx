import { describe, expect, it, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router";
import {
  buildSessionSearch,
  hrefWithSession,
  parseSessionSearch,
  clearFormDraft,
  saveFormDraft,
  loadFormDraft,
} from "./sessionQuery";
import { useSessionQuery } from "./useSessionQuery";

describe("sessionQuery", () => {
  it("parses shareable Streamlit-like keys from search", () => {
    expect(parseSessionSearch("?job=j1&eq=AHU-1&site=b100&section=overview&wl=ECMs")).toEqual({
      jobId: "j1",
      equipment: "AHU-1",
      siteId: "b100",
      section: "overview",
      wattlabPage: "ECMs",
    });
  });

  it("patches search without dropping unrelated params", () => {
    const next = buildSessionSearch("?job=j1&foo=bar", { equipment: "VAV-2", jobId: "" });
    const q = parseSessionSearch(next);
    expect(q.jobId).toBeUndefined();
    expect(q.equipment).toBe("VAV-2");
    expect(next).toContain("foo=bar");
  });

  it("hrefWithSession keeps site and equipment", () => {
    expect(hrefWithSession("/rcx", "?site=BUILDING_100&eq=AHU_1")).toBe(
      "/rcx?eq=AHU_1&site=BUILDING_100",
    );
  });

  it("round-trips form drafts in sessionStorage", () => {
    clearFormDraft("test-draft");
    saveFormDraft("test-draft", { name: "demo" });
    expect(loadFormDraft("test-draft")).toEqual({ name: "demo" });
    clearFormDraft("test-draft");
    expect(loadFormDraft("test-draft")).toBeNull();
  });
});

function SessionProbe() {
  const { query, setQuery } = useSessionQuery();
  return (
    <div>
      <span data-testid="job">{query.jobId ?? ""}</span>
      <span data-testid="eq">{query.equipment ?? ""}</span>
      <button type="button" data-testid="set-job" onClick={() => setQuery({ jobId: "job-9" })}>
        set job
      </button>
      <button
        type="button"
        data-testid="set-eq"
        onClick={() => setQuery({ equipment: "AHU-1" })}
      >
        set eq
      </button>
    </div>
  );
}

function NavProbe() {
  const navigate = useNavigate();
  return (
    <button type="button" data-testid="go-jobs" onClick={() => navigate("/jobs?job=from-nav")}>
      go
    </button>
  );
}

describe("useSessionQuery deep-link / back", () => {
  beforeEach(() => {
    clearFormDraft("test-draft");
  });

  it("restores job from initial URL and updates via setQuery", () => {
    render(
      <MemoryRouter initialEntries={["/jobs?job=seed"]}>
        <Routes>
          <Route path="/jobs" element={<SessionProbe />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("job").textContent).toBe("seed");
    fireEvent.click(screen.getByTestId("set-job"));
    expect(screen.getByTestId("job").textContent).toBe("job-9");
  });

  it("survives navigation to a deep-linked jobs URL", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<NavProbe />} />
          <Route path="/jobs" element={<SessionProbe />} />
        </Routes>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByTestId("go-jobs"));
    expect(screen.getByTestId("job").textContent).toBe("from-nav");
  });
});
