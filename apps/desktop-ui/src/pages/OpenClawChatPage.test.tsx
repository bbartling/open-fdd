import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { OpenClawChatPage } from "./OpenClawChatPage";

describe("OpenClawChatPage", () => {
  it("renders embedded OpenClaw frame and operations sections", () => {
    render(<OpenClawChatPage />);
    expect(screen.getByText("Open-FDD Claw Chat")).toBeInTheDocument();
    expect(screen.getByText("Operations (Cron / Memory / Skills)")).toBeInTheDocument();
    expect(screen.getByTitle("Open-FDD Claw UI")).toBeInTheDocument();
  });

  it("updates cron command preview when draft changes", () => {
    render(<OpenClawChatPage />);
    const nameInput = screen.getAllByLabelText("Job name")[0] as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: "Nightly Portfolio Sweep" } });
    const commandPreview = screen.getAllByLabelText("Cron add command")[0] as HTMLTextAreaElement;
    expect(commandPreview.value).toContain("Nightly Portfolio Sweep");
  });

  it("switches to PowerShell mode and updates memory cleanup command", () => {
    render(<OpenClawChatPage />);
    fireEvent.click(screen.getAllByRole("button", { name: "PowerShell" })[0]);
    const areas = screen.getAllByLabelText("Memory cleanup commands");
    const memoryPreview = areas[0] as HTMLTextAreaElement;
    expect(memoryPreview.value).toContain("Set-Content");
    expect(memoryPreview.value).not.toContain("truncate -s 0");
  });

  it("shows cron validation warning for malformed expression", () => {
    render(<OpenClawChatPage />);
    const cronInput = screen.getAllByLabelText("Cron schedule")[0] as HTMLInputElement;
    fireEvent.change(cronInput, { target: { value: "* * *" } });
    expect(screen.getByText(/Needs attention/i)).toBeInTheDocument();
  });

  it("shows API mode controls when selected", () => {
    render(<OpenClawChatPage />);
    fireEvent.click(screen.getAllByRole("button", { name: "Create via API" })[0]);
    expect(screen.getByLabelText("Endpoint preset")).toBeInTheDocument();
    expect(screen.getByLabelText("API endpoint path")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Create This Job via API/i })).toBeInTheDocument();
    expect(screen.getByLabelText("API request preview (curl)")).toBeInTheDocument();
  });

  it("applies cron helper example button", () => {
    render(<OpenClawChatPage />);
    fireEvent.click(screen.getAllByRole("button", { name: "@hourly" })[0]);
    const cronInput = screen.getAllByLabelText("Cron schedule")[0] as HTMLInputElement;
    expect(cronInput.value).toBe("@hourly");
  });

  it("applies strict cron fallback preset", () => {
    render(<OpenClawChatPage />);
    fireEvent.click(screen.getAllByRole("button", { name: "Apply strict cron fallback" })[0]);
    const failureDestination = screen.getAllByLabelText("Failure destination")[0] as HTMLInputElement;
    const skipped = screen.getAllByLabelText("Alert on skipped runs")[0] as HTMLInputElement;
    expect(failureDestination.value).toBe("ops-alerts");
    expect(skipped.checked).toBe(true);
  });

  it("renders phase 1 policy presets", () => {
    render(<OpenClawChatPage />);
    expect(screen.getAllByText(/Phase 1 policy presets/i)[0]).toBeInTheDocument();
    expect(screen.getAllByText("Runtime route map env preset")[0]).toBeInTheDocument();
    expect(screen.getAllByText("Security safe-defaults preset")[0]).toBeInTheDocument();
  });

  it("renders phase 2 reliability presets", () => {
    render(<OpenClawChatPage />);
    expect(screen.getAllByText(/Phase 2 reliability presets/i)[0]).toBeInTheDocument();
    expect(screen.getAllByText("Strict fallback preset")[0]).toBeInTheDocument();
    expect(screen.getAllByText("Relaxed fallback preset")[0]).toBeInTheDocument();
  });

  it("renders phase 3 memory and subagent presets", () => {
    render(<OpenClawChatPage />);
    expect(screen.getAllByText(/Phase 3 memory \+ multi-site presets/i)[0]).toBeInTheDocument();
    expect(screen.getAllByText("Memory governance preset")[0]).toBeInTheDocument();
    expect(screen.getAllByText("Subagent lanes preset")[0]).toBeInTheDocument();
  });
});

