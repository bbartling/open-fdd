import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { ActionsPage } from "./ActionsPage";

vi.mock("../api/actionsApi", async () => {
  const actual = await vi.importActual<typeof import("../api/actionsApi")>(
    "../api/actionsApi",
  );
  return {
    ...actual,
    listActions: vi.fn(async () => [
      {
        id: "act-1",
        kind: "fdd_run_all",
        label: "Run all",
        started_at: "2026-08-11T12:00:00Z",
        finished_at: "2026-08-11T12:00:02Z",
        duration_ms: 2000,
        status: "ok",
        detail: {},
      },
    ]),
    deleteAction: vi.fn(async () => undefined),
    clearActions: vi.fn(async () => undefined),
  };
});

vi.mock("../api/mappingApi", () => ({
  listPackageBuildings: vi.fn(async () => []),
  getSessionConfig: vi.fn(async () => ({
    ok: true,
    config: { schema_version: "openfdd_session_v1", params: {} },
  })),
  putSessionConfig: vi.fn(async () => ({ ok: true })),
}));

vi.mock("../api/uploadApi", () => ({ uploadPackage: vi.fn() }));

vi.mock("../api/fddApi", () => ({
  listFddRules: vi.fn(async () => []),
  getFddRuleParams: vi.fn(async () => ({ ok: true, params: {} })),
}));

import { clearActions, deleteAction, listActions } from "../api/actionsApi";

describe("ActionsPage housekeeping", () => {
  beforeEach(() => {
    vi.mocked(listActions).mockClear();
    vi.mocked(deleteAction).mockClear();
    vi.mocked(clearActions).mockClear();
  });

  it("requests last 10 and can delete / clear", async () => {
    render(
      <MemoryRouter>
        <ActionsPage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(listActions).toHaveBeenCalledWith(10);
      expect(screen.getByTestId("actions-table")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("actions-delete").querySelector("button")!);
    await waitFor(() => {
      expect(deleteAction).toHaveBeenCalledWith("act-1");
    });
    vi.stubGlobal("confirm", () => true);
    fireEvent.click(screen.getByTestId("actions-clear").querySelector("button")!);
    await waitFor(() => {
      expect(clearActions).toHaveBeenCalled();
    });
    vi.unstubAllGlobals();
  });
});
